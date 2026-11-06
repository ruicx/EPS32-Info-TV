"""Exercise automatic weather against a fake HTTP provider, without internet."""

import asyncio
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import OfflineTransport

from info_tv_service.app import create_app
from info_tv_service.config import Settings, WeatherSettings
from info_tv_service.device.generated import device_pb2 as pb
from info_tv_service.device.session import DeviceSession
from info_tv_service.tasks.store import TaskStore
from info_tv_service.weather import WeatherUpdater, weather_condition


@pytest.mark.parametrize("code,expected", [
    (0, pb.WEATHER_CONDITION_CLEAR), (1, pb.WEATHER_CONDITION_CLEAR),
    (3, pb.WEATHER_CONDITION_CLOUDY), (48, pb.WEATHER_CONDITION_FOG),
    (67, pb.WEATHER_CONDITION_RAIN), (86, pb.WEATHER_CONDITION_SNOW),
    (95, pb.WEATHER_CONDITION_STORM), (97, pb.WEATHER_CONDITION_STORM),
    (999, pb.WEATHER_CONDITION_UNKNOWN),
])
def test_weather_code_mapping(code: int, expected: int) -> None:
    """Map documented condition families without inventing official alerts.

    Parameters
    ----------
    code : int
        WMO source code.
    expected : int
        Device icon enum.
    """
    assert weather_condition(code) == expected


@pytest.mark.parametrize("failure", ["timeout", "http", "json", "missing", "stale", "future", "range", "nan"])
def test_fetch_failure_retains_weather_and_success_recovers(failure: str) -> None:
    """Failures preserve the last published weather and are cleared by recovery.

    Parameters
    ----------
    failure : str
        Provider failure injected after a valid update.
    """
    async def scenario() -> None:
        """Drive production parsing/publication through an HTTP mock."""
        now = int(time.time())
        mode = "valid"
        settings = WeatherSettings(location="Shanghai", latitude=31.2304, longitude=121.4737)
        store = TaskStore()
        device = DeviceSession(OfflineTransport(), store.list_tasks)
        updater = WeatherUpdater(settings, device)

        def respond(request: httpx.Request) -> httpx.Response:
            """Return valid or deliberately broken provider data.

            Parameters
            ----------
            request : Request
                Captured provider request.

            Returns
            -------
            Response
                Injected JSON or HTTP failure.

            Raises
            ------
            ReadTimeout
                For an injected network timeout.
            """
            assert request.url.params["timezone"] == "auto"
            assert request.url.params["forecast_days"] == "1"
            if mode == "timeout":
                raise httpx.ReadTimeout("offline", request=request)
            if mode == "http":
                return httpx.Response(503)
            if mode == "json":
                return httpx.Response(200, text="not json")
            if mode == "missing":
                return httpx.Response(200, json={"current": {"temperature_2m": None}})
            timestamp = now - 1000
            if mode == "stale":
                timestamp = now - 4000
            if mode == "future":
                timestamp = now + 4000
            return httpx.Response(200, json={
                "current": {"time": timestamp, "temperature_2m": 20.6, "weather_code": 2},
                "daily": {"time": [now - 3600], "temperature_2m_min": [25 if mode == "range" else 16.2],
                          "temperature_2m_max": ["NaN" if mode == "nan" else 23.8]},
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await updater.refresh(client)
            before = device.weather_status()
            assert before["temperature_c"] == 21
            assert before["daily_low_c"] == 16
            assert before["daily_high_c"] == 24
            assert 0 < int(str(before["valid_for_ms"])) <= 800_000
            success = updater.last_success
            mode = failure
            assert not await updater.refresh(client)
            assert updater.last_error is not None
            assert updater.last_success == success
            after = device.weather_status()
            assert after["temperature_c"] == before["temperature_c"]
            assert int(str(after["valid_for_ms"])) <= int(str(before["valid_for_ms"]))
            mode = "valid"
            assert await updater.refresh(client)
            assert updater.last_error is None
            assert updater.source_time == now - 1000
            assert int(str(device.weather_status()["valid_for_ms"])) <= 800_000
    asyncio.run(scenario())


def test_automatic_startup_retries_failure_and_closes_http_client() -> None:
    """The application lifespan owns startup retrieval, retries, and shutdown."""
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        """Fail once, then supply current Shanghai model data.

        Parameters
        ----------
        request : Request
            Provider request.

        Returns
        -------
        Response
            Failure followed by valid weather.
        """
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        now = int(time.time())
        return httpx.Response(200, json={
            "current": {"time": now, "temperature_2m": 18, "weather_code": 61},
            "daily": {"time": [now - 3600], "temperature_2m_min": [15], "temperature_2m_max": [22]},
        })

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    settings = Settings("unused", weather=WeatherSettings(location="Shanghai", latitude=31, longitude=121, retry_seconds=1))
    with (
        patch("info_tv_service.weather.httpx.AsyncClient", return_value=http_client),
        TestClient(create_app(settings, OfflineTransport())) as client,
    ):
        deadline = time.monotonic() + 4
        while not client.get("/v1/weather/updater").json()["last_success"]:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert attempts == 2
        assert client.get("/v1/weather/updater").json()["last_error"] is None
        assert client.get("/v1/weather").json()["condition"] == "rain"
    assert http_client.is_closed
