"""Exercise production request validation and independent application lifetimes."""

import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from info_tv_service.app import create_app
from info_tv_service.config import Settings


class OfflineTransport:
    """Fail opening without accessing a real serial port."""

    async def open(self) -> None:
        """Report the deliberately absent device."""
        raise OSError("offline test device")

    async def close(self) -> None:
        """Release the test transport's empty resource set."""

    async def read(self) -> bytes:
        """Reject reads on the absent device.

        Raises
        ------
        OSError
            Always, because this fixture is offline.
        """
        raise OSError("offline")

    async def write(self, data: bytes) -> None:
        """Reject writes on the absent device.

        Parameters
        ----------
        data : bytes
            Unsent data.

        Raises
        ------
        OSError
            Always, because this fixture is offline.
        """
        raise OSError("offline")


def body() -> dict[str, object]:
    """Return one valid completion request.

    Returns
    -------
    dict[str, object]
        JSON-compatible submission.
    """
    return {"event_id": uuid4().hex, "source": "test", "task_id": "run", "sequence": 1,
            "state": "completed", "title": "Build", "progress_percent": 100}


def test_offline_acceptance_duplicate_and_app_isolation() -> None:
    """HTTP admission is independent of delivery and isolated per app."""
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        submission = body()
        response = client.post("/v1/task-events", json=submission)
        assert response.status_code == 202
        assert response.json()["notification"] == "skipped_offline"
        assert client.post("/v1/task-events", json=submission).json()["outcome"] == "duplicate"
        assert len(client.get("/v1/tasks").json()) == 1
        assert client.get("/v1/tasks").json()[0]["delivery"] == {"state": "pending"}
        assert client.get("/v1/tasks").json()[0]["icon"] == "task"
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as other:
        assert other.get("/v1/tasks").json() == []


def test_close_is_idempotent_offline_and_blocks_late_run_updates() -> None:
    """Manual removal releases capacity without relying on an online device."""
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        submission = body()
        response = client.post("/v1/task-events", json=submission)
        card_id = response.json()["card_id"]
        assert client.delete(f"/v1/tasks/{card_id}").json()["removed"]
        assert not client.delete(f"/v1/tasks/{card_id}").json()["removed"]
        assert client.get("/v1/tasks").json() == []
        submission.update(event_id=uuid4().hex, sequence=2)
        assert client.post("/v1/task-events", json=submission).json()["outcome"] == "closed"
        assert client.get("/v1/weather/updater").json() == {"enabled": False}


def test_completed_tasks_expire_without_another_submission() -> None:
    """The lifespan maintenance loop cleans completed tasks autonomously."""
    with TestClient(create_app(Settings("unused", completed_retention_seconds=1), OfflineTransport())) as client:
        assert client.post("/v1/task-events", json=body()).status_code == 202
        deadline = time.monotonic() + 4
        while client.get("/v1/tasks").json():
            assert time.monotonic() < deadline
            time.sleep(0.02)


@pytest.mark.parametrize("field,value", [
    ("progress_percent", 101), ("progress_percent", True), ("sequence", 0),
    ("title", "\0bad"), ("title", "界" * 30), ("state", "mystery"),
    ("screen_x", 20), ("detail", "x" * 161),
    ("conversation_id", "thread"), ("run_sequence", 1),
    ("conversation_title", "Unidentified conversation"), ("context", "界" * 22),
    ("icon", "unknown"), ("icon", 2), ("icon", None),
])
def test_invalid_requests_do_not_enter_state(field: str, value: object) -> None:
    """Invalid or device-specific input never changes accepted task state.

    Parameters
    ----------
    field : str
        Input field to replace or introduce.
    value : object
        Invalid JSON-compatible value.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        submission = body()
        submission[field] = value
        assert client.post("/v1/task-events", json=submission).status_code == 422
        assert client.get("/v1/tasks").json() == []


def test_conversation_fields_round_trip_and_update_one_card() -> None:
    """Multiple runs retain one card while preserving display labels and ordinals."""
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        submission = body()
        submission.update(conversation_id="thread", conversation_title="消息接口", icon="test",
                          context="info_tv", run_sequence=1)
        first = client.post("/v1/task-events", json=submission)
        assert first.status_code == 202
        submission.update(event_id=uuid4().hex, task_id="next-run", run_sequence=2, state="running")
        second = client.post("/v1/task-events", json=submission)
        assert second.status_code == 202
        assert first.json()["card_id"] == second.json()["card_id"]
        records = client.get("/v1/tasks").json()
        assert len(records) == 1
        assert records[0]["conversation_title"] == "消息接口"
        assert records[0]["run_sequence"] == 2
        assert records[0]["context"] == "info_tv"
        assert records[0]["icon"] == "test"
        submission["icon"] = "build"
        assert client.post("/v1/task-events", json=submission).status_code == 409


def test_offline_brightness_is_pending_and_isolated_per_app() -> None:
    """Retain offline zero without claiming application or creating a task."""
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        response = client.put("/v1/device/settings", json={"brightness_percent": 0})
        assert response.status_code == 202
        assert response.json() == {"brightness_percent": 0, "applied_brightness_percent": None,
                                   "delivery": {"state": "pending"}}
        assert client.get("/v1/device/settings").json() == response.json()
        assert client.get("/v1/device").json()["settings"] == response.json()
        assert client.get("/v1/tasks").json() == []
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as other:
        assert other.get("/v1/device/settings").json()["brightness_percent"] == 100


@pytest.mark.parametrize("submission", [
    {}, {"brightness_percent": -1}, {"brightness_percent": 101},
    {"brightness_percent": True}, {"brightness_percent": 30.5},
    {"brightness_percent": "30"}, {"brightness_percent": None},
    {"brightness_percent": 30, "screen_x": 2},
])
def test_invalid_brightness_preserves_target(submission: dict[str, object]) -> None:
    """Reject malformed settings without changing the retained target.

    Parameters
    ----------
    submission : dict[str, object]
        Invalid settings body.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        assert client.put("/v1/device/settings", json=submission).status_code == 422
        assert client.get("/v1/device/settings").json()["brightness_percent"] == 100


def test_weather_is_independent_offline_clearable_and_isolated() -> None:
    """Retain real zero-degree weather without taking a task slot."""
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        assert client.get("/v1/weather").json()["state"] == "unavailable"
        weather = {"location": "Harbin", "temperature_c": 0, "condition": "snow"}
        response = client.put("/v1/weather", json=weather)
        assert response.status_code == 202
        assert response.json()["state"] == "fresh"
        assert response.json()["temperature_c"] == 0
        assert response.json()["delivery"] == {"state": "pending"}
        assert client.get("/v1/tasks").json() == []
        assert client.get("/v1/device").json()["weather"]["location"] == "Harbin"
        assert client.delete("/v1/weather").json()["state"] == "unavailable"
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as other:
        assert other.get("/v1/weather").json()["state"] == "unavailable"


@pytest.mark.parametrize("field,value", [
    ("location", ""), ("location", "   "), ("location", "\0city"),
    ("location", "city\n"), ("location", "\x7fcity"), ("location", "界" * 9), ("location", 123),
    ("temperature_c", True), ("temperature_c", "23"), ("temperature_c", 23.5),
    ("temperature_c", None), ("temperature_c", -101), ("temperature_c", 101),
    ("condition", "typhoon"), ("valid_for_seconds", 0), ("valid_for_seconds", 3601),
    ("valid_for_seconds", True), ("screen_x", 20),
])
def test_invalid_weather_does_not_replace_values(field: str, value: object) -> None:
    """Reject malformed weather without altering the retained observation.

    Parameters
    ----------
    field : str
        Field to replace or introduce.
    value : object
        Invalid JSON input.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        weather: dict[str, object] = {"location": "Shanghai", "temperature_c": 23, "condition": "clear"}
        assert client.put("/v1/weather", json=weather).status_code == 202
        weather[field] = value
        assert client.put("/v1/weather", json=weather).status_code == 422
        assert client.get("/v1/weather").json()["temperature_c"] == 23


@pytest.mark.parametrize("extra", [
    {"daily_low_c": 10}, {"daily_high_c": 20},
    {"daily_low_c": 25, "daily_high_c": 20},
    {"daily_low_c": True, "daily_high_c": 20},
    {"daily_low_c": -101, "daily_high_c": 20},
    {"daily_low_c": 10, "daily_high_c": "20"},
])
def test_daily_range_is_optional_paired_and_ordered(extra: dict[str, object]) -> None:
    """Reject incomplete or malformed ranges without replacing accepted weather.

    Parameters
    ----------
    extra : dict[str, object]
        Invalid range fields.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        weather = {"location": "Harbin", "temperature_c": 0, "condition": "snow"}
        assert client.put("/v1/weather", json=weather | {"daily_low_c": -10, "daily_high_c": 0}).status_code == 202
        assert client.put("/v1/weather", json=weather | extra).status_code == 422
        assert client.get("/v1/weather").json()["daily_low_c"] == -10
        assert client.get("/v1/weather").json()["daily_high_c"] == 0
        assert client.put("/v1/weather", json=weather).json()["daily_low_c"] is None


def alert_body() -> dict[str, object]:
    """Construct a synthetic alert without suggesting it is an actual warning.

    Returns
    -------
    dict[str, object]
        Valid producer request with a stable identity per call.
    """
    return {"alert_id": uuid4().hex, "sequence": 1, "title": "Rain", "source": "Demo bureau",
            "location": "Shanghai", "severity": "orange", "detail": "Synthetic preview only.",
            "valid_for_seconds": 3600}


def test_alert_ordering_idempotence_and_independent_clear() -> None:
    """Keep alerts independent of weather, task count, and identical retries."""
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        alert = alert_body()
        first = client.put("/v1/weather/alert", json=alert)
        assert first.status_code == 202 and first.json()["state"] == "active"
        assert first.json()["notification"] == "skipped_offline"
        retry = client.put("/v1/weather/alert", json=alert)
        assert retry.json()["valid_for_ms"] <= first.json()["valid_for_ms"]
        assert client.put("/v1/weather/alert", json=alert | {"title": "Changed"}).status_code == 409
        assert client.put("/v1/weather/alert", json=alert | {"sequence": 2}).status_code == 202
        assert client.put("/v1/weather/alert", json=alert).status_code == 409
        assert client.delete("/v1/weather").status_code == 202
        assert client.get("/v1/weather/alert").json()["state"] == "active"
        assert client.get("/v1/tasks").json() == []
        assert client.delete("/v1/weather/alert").json()["state"] == "unavailable"
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as other:
        assert other.get("/v1/weather/alert").json()["state"] == "unavailable"


@pytest.mark.parametrize("field,value", [
    ("alert_id", "invalid"), ("sequence", 0), ("sequence", True),
    ("severity", "purple"), ("severity", 3), ("source", " "),
    ("title", "\0Rain"), ("title", "界" * 22), ("location", "界" * 9),
    ("detail", "line\nbreak"), ("valid_for_seconds", 0), ("valid_for_seconds", 86401),
])
def test_invalid_alert_preserves_current(field: str, value: object) -> None:
    """Reject malformed alerts before mutating the current slot.

    Parameters
    ----------
    field : str
        Field to replace.
    value : object
        Invalid JSON value.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as client:
        alert = alert_body()
        assert client.put("/v1/weather/alert", json=alert).status_code == 202
        assert client.put("/v1/weather/alert", json=alert | {field: value}).status_code == 422
        assert client.get("/v1/weather/alert").json()["title"] == "Rain"
