"""Exercise production request validation and independent application lifetimes."""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

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
