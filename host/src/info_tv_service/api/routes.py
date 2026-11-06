"""Local HTTP route handlers using explicit lifecycle-owned dependencies."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request

from info_tv_service.api.models import DeviceSettingsRequest, TaskEventRequest, WeatherAlertRequest, WeatherRequest
from info_tv_service.device.generated import device_pb2 as pb
from info_tv_service.runtime import ServiceRuntime
from info_tv_service.tasks.store import AdmissionError


def runtime_from_request(request: Request) -> ServiceRuntime:
    """Resolve the runtime initialized by the application lifespan.

    Parameters
    ----------
    request : Request
        Current HTTP request.

    Returns
    -------
    ServiceRuntime
        Application-owned state and services.
    """
    return cast(ServiceRuntime, request.app.state.runtime)


def create_router() -> APIRouter:
    """Create a router without module-global mutable objects.

    Returns
    -------
    APIRouter
        Producer and diagnostics endpoints.
    """
    router = APIRouter(prefix="/v1")

    @router.post("/task-events", status_code=202)
    async def submit_event(body: TaskEventRequest, request: Request) -> dict[str, object]:
        """Admit a producer update without awaiting device presentation.

        Parameters
        ----------
        body : TaskEventRequest
            Validated JSON body.
        request : Request
            Request carrying the application context.

        Returns
        -------
        dict[str, object]
            Admission and notification disposition.

        Raises
        ------
        HTTPException
            For invalid encoded text, conflicts, or exhausted capacity.
        """
        runtime = runtime_from_request(request)
        if runtime.failure:
            raise HTTPException(503, "Device coordinator failed")
        try:
            return runtime.tasks.submit_event(body.to_event())
        except AdmissionError as error:
            raise HTTPException(error.status_code, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/tasks")
    async def list_tasks(request: Request) -> list[dict[str, object]]:
        """List accepted business state and actual device milestones.

        Parameters
        ----------
        request : Request
            Request carrying the application context.

        Returns
        -------
        list[dict[str, object]]
            Independent task records and latest sent revisions.
        """
        runtime = runtime_from_request(request)
        return [
            {"source": record.event.source, "task_id": record.event.task_id,
             "state": record.event.state, "title": record.event.title,
             "detail": record.event.detail, "progress_percent": record.event.progress_percent,
             "icon": record.event.icon,
             "conversation_id": record.event.conversation_id,
             "conversation_title": record.event.conversation_title,
             "context": record.event.context, "run_sequence": record.event.run_sequence,
             "sequence": record.event.sequence, "revision": record.revision,
             "card_id": record.card_id, "delivery": runtime.device.card_status(record.card_id)}
            for record in runtime.store.list_tasks()
        ]

    @router.put("/device/settings", status_code=202)
    async def set_device_settings(body: DeviceSettingsRequest, request: Request) -> dict[str, object]:
        """Retain the target brightness until the device reports application.

        Parameters
        ----------
        body : DeviceSettingsRequest
            Validated absolute brightness level.
        request : Request
            Request carrying the application context.

        Returns
        -------
        dict[str, object]
            Target, last reported value, and delivery status.

        Raises
        ------
        HTTPException
            If the device coordinator stopped unexpectedly.
        """
        runtime = runtime_from_request(request)
        if runtime.failure:
            raise HTTPException(503, runtime.failure)
        runtime.device.set_brightness(body.brightness_percent)
        return runtime.device.settings_status()

    @router.get("/device/settings")
    async def device_settings(request: Request) -> dict[str, object]:
        """Query desired brightness and actual device application feedback.

        Parameters
        ----------
        request : Request
            Request carrying the application context.

        Returns
        -------
        dict[str, object]
            Target, last reported value, and delivery status.
        """
        return runtime_from_request(request).device.settings_status()

    @router.put("/weather", status_code=202)
    async def set_weather(body: WeatherRequest, request: Request) -> dict[str, object]:
        """Retain weather independently of the conversation card limit.

        Parameters
        ----------
        body : WeatherRequest
            Validated current conditions with remaining freshness.
        request : Request
            Application context.

        Returns
        -------
        dict[str, object]
            Weather freshness and delivery admission.

        Raises
        ------
        HTTPException
            If the device coordinator failed.
        """
        runtime = runtime_from_request(request)
        if runtime.failure:
            raise HTTPException(503, runtime.failure)
        weather = pb.Weather(
            location=body.location, temperature_c=body.temperature_c,
            condition=f"WEATHER_CONDITION_{body.condition.upper()}",
            valid_for_ms=body.valid_for_seconds * 1000,
        )
        if body.daily_low_c is not None and body.daily_high_c is not None:
            weather.daily_low_c = body.daily_low_c
            weather.daily_high_c = body.daily_high_c
        runtime.device.set_weather(weather)
        return runtime.device.weather_status()

    @router.get("/weather")
    async def weather_status(request: Request) -> dict[str, object]:
        """Query retained weather without claiming it is still fresh.

        Parameters
        ----------
        request : Request
            Application context.

        Returns
        -------
        dict[str, object]
            Unavailable, fresh, or stale weather and delivery status.
        """
        return runtime_from_request(request).device.weather_status()

    @router.delete("/weather", status_code=202)
    async def clear_weather(request: Request) -> dict[str, object]:
        """Clear the retained weather and queue its removal on the device.

        Parameters
        ----------
        request : Request
            Application context.

        Returns
        -------
        dict[str, object]
            Unavailable weather with pending delivery.

        Raises
        ------
        HTTPException
            If the device coordinator failed.
        """
        runtime = runtime_from_request(request)
        if runtime.failure:
            raise HTTPException(503, runtime.failure)
        runtime.device.set_weather(pb.Weather())
        return runtime.device.weather_status()

    @router.put("/weather/alert", status_code=202)
    async def set_weather_alert(body: WeatherAlertRequest, request: Request) -> dict[str, object]:
        """Admit one ordered alert independently of ordinary weather freshness.

        Parameters
        ----------
        body : WeatherAlertRequest
            Source-selected alert and remaining validity.
        request : Request
            Application context.

        Returns
        -------
        dict[str, object]
            Retained alert, notification disposition, and device admission.

        Raises
        ------
        HTTPException
            For conflicting updates or a failed coordinator.
        """
        runtime = runtime_from_request(request)
        if runtime.failure:
            raise HTTPException(503, runtime.failure)
        alert = pb.WeatherAlert(
            alert_id=body.alert_id.hex, title=body.title, source=body.source,
            location=body.location, detail=body.detail,
            severity=f"WEATHER_ALERT_SEVERITY_{body.severity.upper()}",
            valid_for_ms=body.valid_for_seconds * 1000,
        )
        try:
            runtime.device.set_weather_alert(alert, body.sequence)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return runtime.device.weather_alert_status()

    @router.get("/weather/alert")
    async def weather_alert_status(request: Request) -> dict[str, object]:
        """Query alert validity independently of notification dismissal.

        Parameters
        ----------
        request : Request
            Application context.

        Returns
        -------
        dict[str, object]
            Retained alert and latest device feedback.
        """
        return runtime_from_request(request).device.weather_alert_status()

    @router.delete("/weather/alert", status_code=202)
    async def clear_weather_alert(request: Request) -> dict[str, object]:
        """Withdraw the current alert and its pending or active notification.

        Parameters
        ----------
        request : Request
            Application context.

        Returns
        -------
        dict[str, object]
            Empty alert state with pending removal delivery.

        Raises
        ------
        HTTPException
            If the coordinator failed.
        """
        runtime = runtime_from_request(request)
        if runtime.failure:
            raise HTTPException(503, runtime.failure)
        runtime.device.set_weather_alert(pb.WeatherAlert(), 0)
        return runtime.device.weather_alert_status()

    @router.get("/device")
    async def device_status(request: Request) -> dict[str, object]:
        """Report connection, feedback, and coordinator health.

        Parameters
        ----------
        request : Request
            Request carrying the application context.

        Returns
        -------
        dict[str, object]
            Device diagnostics.

        Raises
        ------
        HTTPException
            If an unexpected background task failure stopped delivery.
        """
        runtime = runtime_from_request(request)
        if runtime.failure:
            raise HTTPException(503, runtime.failure)
        return runtime.device.get_status()

    return router
