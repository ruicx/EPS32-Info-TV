"""Local HTTP route handlers using explicit lifecycle-owned dependencies."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request

from info_tv_service.api.models import TaskEventRequest
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
