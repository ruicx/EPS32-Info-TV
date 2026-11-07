"""Replay real Codex payloads through persistent ordering and the host API."""

import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import OfflineTransport

from info_tv_service.api.models import TaskEventRequest
from info_tv_service.app import create_app
from info_tv_service.config import Settings
from info_tv_service.hooks.cli import flush_pending, main
from info_tv_service.hooks.codex import CodexHook
from info_tv_service.hooks.store import CodexStore
from info_tv_service.tasks.models import TaskState


def hook(name: str, turn: str = "turn-1", session: str = "session-1", **changes: object) -> CodexHook:
    """Reuse captured native fields with explicit test identities.

    Parameters
    ----------
    name : str
        Captured callback name.
    turn : str
        Execution identity.
    session : str
        Conversation identity.
    **changes : object
        Payload fields to replace.

    Returns
    -------
    CodexHook
        Validated callback built from a real captured sample.
    """
    evidence = Path(__file__).resolve().parents[2] / "docs/evidence/codex-hooks-2026-11-07.json"
    samples = json.loads(evidence.read_text(encoding="utf-8"))["representative_captures"]
    payload = samples[name]["payload"] | {"session_id": session, "turn_id": turn} | changes
    return CodexHook.model_validate(payload)


def test_capture_orders_runs_across_processes_and_bounds_utf8(tmp_path: Path) -> None:
    """Retain independent cards, immutable labels, and monotonic run identities.

    Parameters
    ----------
    tmp_path : Path
        Private persistent ledger directory.
    """
    path = tmp_path / "state.sqlite3"
    events = [hook("UserPromptSubmit", prompt="修复接口\n" * 40, cwd="D:\\项目\\显示屏"),
              hook("PreToolUse"), hook("PermissionRequest"), hook("PostToolUse"), hook("Stop"),
              hook("Stop"), hook("PreToolUse"), hook("UserPromptSubmit"),
              hook("UserPromptSubmit", turn="turn-2", prompt="Next task"),
              hook("UserPromptSubmit", turn="other-turn", session="other-session", prompt="Same workspace")]
    submissions = []
    for event in events:
        with closing(CodexStore(path)) as store:
            submission = store.capture(event)
            if submission is not None:
                submissions.append(submission)
    assert [s.state for s in submissions] == [TaskState.RUNNING, TaskState.WAITING_INPUT,
                                            TaskState.RUNNING, TaskState.COMPLETED,
                                            TaskState.RUNNING, TaskState.RUNNING]
    assert [s.sequence for s in submissions] == [1, 2, 3, 4, 1, 1]
    assert [s.run_sequence for s in submissions] == [1, 1, 1, 1, 2, 1]
    assert len(submissions[0].title.encode("utf-8")) <= 64
    assert submissions[0].context == "显示屏"
    assert "\n" not in submissions[0].title
    assert submissions[4].conversation_title == submissions[0].title
    assert all(s.progress_percent is None for s in submissions)


def test_unknown_terminal_and_interrupted_runs_cannot_be_revived(tmp_path: Path) -> None:
    """Late terminal/activity callbacks neither allocate runs nor reopen them.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    """
    with closing(CodexStore(tmp_path / "state.sqlite3")) as store:
        assert store.capture(hook("Interrupt", turn="never-started")) is None
        assert store.capture(hook("UserPromptSubmit", turn="never-started")) is None
        first = store.capture(hook("UserPromptSubmit"))
        assert first is not None and first.run_sequence == 1
        stopped = store.capture(hook("Interrupt"))
        assert stopped is not None and stopped.state == TaskState.INTERRUPTED
        for name in ["Stop", "PreToolUse", "PostToolUse", "PermissionRequest", "UserPromptSubmit", "Interrupt"]:
            assert store.capture(hook(name)) is None
        second = store.capture(hook("UserPromptSubmit", turn="turn-2"))
        assert second is not None and second.run_sequence == 2
        assert store.capture(hook("Stop", turn="another-unknown")) is None


def test_parallel_callbacks_allocate_unique_ordinals(tmp_path: Path) -> None:
    """Independent callback connections cannot allocate the same execution number.

    Parameters
    ----------
    tmp_path : Path
        Shared ledger directory.
    """
    path = tmp_path / "state.sqlite3"

    def capture(index: int) -> int:
        """Open one callback connection and allocate one run.

        Parameters
        ----------
        index : int
            Distinct native turn identity.

        Returns
        -------
        int
            Committed conversation ordinal.
        """
        with closing(CodexStore(path)) as store:
            submission = store.capture(hook("UserPromptSubmit", turn=f"parallel-{index}"))
            assert submission is not None and submission.run_sequence is not None
            return submission.run_sequence

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sorted(executor.map(capture, range(6))) == list(range(1, 7))


def test_uncertain_http_delivery_retries_exact_payload_against_real_api(tmp_path: Path) -> None:
    """An accepted request whose reply was lost is deduplicated after restart.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    """
    path = tmp_path / "state.sqlite3"
    bodies: list[bytes] = []
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as api:
        def forward(request: httpx.Request) -> httpx.Response:
            """Lose only the first acknowledgment after actual admission.

            Parameters
            ----------
            request : httpx.Request
                Original sender request.

            Returns
            -------
            httpx.Response
                Real API admission response on retry.

            Raises
            ------
            httpx.ReadTimeout
                After accepting the first request.
            """
            bodies.append(request.content)
            response = api.post("/v1/task-events", content=request.content,
                                headers={"Content-Type": "application/json"})
            if len(bodies) == 1:
                raise httpx.ReadTimeout("Acknowledgment lost", request=request)
            return response

        with closing(CodexStore(path)) as store, httpx.Client(transport=httpx.MockTransport(forward)) as client:
            store.capture(hook("UserPromptSubmit"))
            with pytest.raises(httpx.ReadTimeout):
                flush_pending(store, client, "http://127.0.0.1:8765")
            assert store.next_pending() is not None
        with closing(CodexStore(path)) as store, httpx.Client(transport=httpx.MockTransport(forward)) as client:
            flush_pending(store, client, "http://127.0.0.1:8765")
            assert store.next_pending() is None
        assert len(bodies) == 2 and bodies[0] == bodies[1]
        records = api.get("/v1/tasks").json()
        assert len(records) == 1 and records[0]["revision"] == 1


def test_queue_replays_late_runs_without_overwriting_newer_conversation(tmp_path: Path) -> None:
    """Source ordinals protect the current card when an old run ends late.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as api:
        def forward(request: httpx.Request) -> httpx.Response:
            """Submit queued JSON to the actual route.

            Parameters
            ----------
            request : httpx.Request
                Sender request.

            Returns
            -------
            httpx.Response
                Actual host admission.
            """
            return api.post("/v1/task-events", content=request.content,
                            headers={"Content-Type": "application/json"})

        with closing(CodexStore(tmp_path / "state.sqlite3")) as store:
            for event in [hook("UserPromptSubmit"), hook("UserPromptSubmit", turn="turn-2"),
                          hook("Stop"), hook("UserPromptSubmit", turn="turn-3", session="session-2"),
                          hook("Interrupt", turn="turn-2")]:
                store.capture(event)
            with httpx.Client(transport=httpx.MockTransport(forward)) as client:
                flush_pending(store, client, "http://127.0.0.1:8765")
            records = api.get("/v1/tasks").json()
            assert len(records) == 2
            current = next(record for record in records if record["conversation_id"] == "session-1")
            assert current["task_id"] == "turn-2" and current["state"] == "interrupted"
            assert current["run_sequence"] == 2


@pytest.mark.parametrize("status,body", [
    (503, {"detail": "busy"}), (202, {"outcome": "unknown"}),
    (202, {"outcome": ["accepted"]}), (200, {}),
])
def test_unacknowledged_events_remain_pending(tmp_path: Path, status: int, body: dict[str, object]) -> None:
    """Only a recognized task admission response can remove retry data.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    status : int
        Unsuccessful or unexpected HTTP status.
    body : dict[str, object]
        Invalid acknowledgment content.
    """
    with closing(CodexStore(tmp_path / "state.sqlite3")) as store:
        store.capture(hook("UserPromptSubmit"))
        original = store.next_pending()
        with (httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))) as client,
              pytest.raises((ValueError, httpx.HTTPStatusError))):
            flush_pending(store, client, "http://127.0.0.1:8765")
        assert store.next_pending() == original


def test_cli_utf8_input_and_failed_delivery_are_neutral(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Windows pipe input preserves Unicode while a down host cannot block Codex.

    Parameters
    ----------
    tmp_path : Path
        Private state directory.
    capsys : pytest.CaptureFixture[str]
        Hook stdout/stderr capture.
    """
    path = tmp_path / "state.sqlite3"
    native = hook("UserPromptSubmit", prompt="修复中文接口").model_dump_json().encode("utf-8")

    def fail(request: httpx.Request) -> httpx.Response:
        """Simulate an absent host.

        Parameters
        ----------
        request : httpx.Request
            Sender request.

        Raises
        ------
        httpx.ConnectError
            Always, leaving the event queued.
        """
        raise httpx.ConnectError("offline", request=request)

    with io.TextIOWrapper(io.BytesIO(native)) as stdin:
        client = httpx.Client(transport=httpx.MockTransport(fail))
        with patch.object(sys, "stdin", stdin), patch("info_tv_service.hooks.cli.httpx.Client", return_value=client):
            main(["codex", "--state-file", str(path)])
    output = capsys.readouterr()
    assert output.out == "{}\n" and "offline" in output.err
    with closing(CodexStore(path)) as store:
        pending = store.next_pending()
        assert pending is not None
        assert TaskEventRequest.model_validate_json(pending[1]).title == "修复中文接口"


def test_cli_invalid_input_is_neutral_without_creating_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Malformed native JSON cannot return a blocking hook decision or exit code.

    Parameters
    ----------
    tmp_path : Path
        Private state directory.
    capsys : pytest.CaptureFixture[str]
        Hook output capture.
    """
    path = tmp_path / "state.sqlite3"
    with (io.TextIOWrapper(io.BytesIO(b'{"hook_event_name":"UserPromptSubmit"}')) as stdin,
          patch.object(sys, "stdin", stdin)):
        main(["codex", "--state-file", str(path)])
    output = capsys.readouterr()
    assert output.out == "{}\n" and "info-tv-hook:" in output.err
    assert not path.exists()
