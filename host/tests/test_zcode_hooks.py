"""Replay native ZCode callbacks through ordering, retry, and the common API."""

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
from info_tv_service.hooks.agy import AgyHook
from info_tv_service.hooks.agy_store import AgyStore
from info_tv_service.hooks.cli import default_state_path, flush_pending, main
from info_tv_service.hooks.codex import CodexHook
from info_tv_service.hooks.store import CodexStore
from info_tv_service.hooks.zcode import ZcodeHook
from info_tv_service.hooks.zcode_store import ZcodeStore
from info_tv_service.tasks.models import TaskState


def evidence() -> dict[str, object]:
    """Load sanitized captures from the installed native ZCode runtime.

    Returns
    -------
    dict[str, object]
        Published capture bundle.
    """
    path = Path(__file__).resolve().parents[2] / "docs/evidence/zcode-hooks-2026-11-07.json"
    return json.loads(path.read_text(encoding="utf-8"))


def hook(name: str, turn: str = "turn-1", session: str = "session-1", **changes: object) -> ZcodeHook:
    """Use real native fields with explicit identity and payload overrides.

    Parameters
    ----------
    name : str
        Captured event name.
    turn : str
        Native execution identity.
    session : str
        Native conversation identity.
    **changes : object
        Fields to replace in the recorded payload.

    Returns
    -------
    ZcodeHook
        Validated callback.
    """
    samples = evidence()["representative_captures"]
    assert isinstance(samples, dict)
    return ZcodeHook.model_validate(samples[name]["payload"] | {
        "session_id": session, "sessionId": session, "turnId": turn,
    } | changes)


def test_real_timeline_preserves_turn_identity_and_cancellation_gap(tmp_path: Path) -> None:
    """Six native turns retain distinct runs despite repeated prompts and cancellation.

    Parameters
    ----------
    tmp_path : Path
        Ledger directory shared by independent callback connections.
    """
    timeline = evidence()["timeline"]
    assert isinstance(timeline, list)
    submissions = []
    for payload in timeline:
        with closing(ZcodeStore(tmp_path / "state.sqlite3")) as store:
            result = store.capture(ZcodeHook.model_validate(payload))
            if result is not None:
                submissions.append(result)
    assert [s.run_sequence for s in submissions] == [1, 1, 2, 2, 2, 2, 2, 2, 3, 3, 4, 5, 5, 6, 6]
    assert [s.state for s in submissions] == [
        TaskState.RUNNING, TaskState.COMPLETED,
        TaskState.RUNNING, TaskState.WAITING_INPUT, TaskState.RUNNING,
        TaskState.WAITING_INPUT, TaskState.RUNNING, TaskState.COMPLETED,
        TaskState.RUNNING, TaskState.COMPLETED, TaskState.RUNNING,
        TaskState.RUNNING, TaskState.COMPLETED, TaskState.RUNNING, TaskState.COMPLETED,
    ]
    assert [s.sequence for s in submissions[2:8]] == [1, 2, 3, 4, 5, 6]
    assert len({s.task_id for s in submissions}) == 6
    assert submissions[-1].task_id != submissions[-3].task_id
    assert all(s.source == "zcode" and s.progress_percent is None for s in submissions)


def test_terminal_replays_and_unstarted_activity_cannot_reopen_runs(tmp_path: Path) -> None:
    """Unknown stops leave tombstones and late activity cannot revive closed turns.

    Parameters
    ----------
    tmp_path : Path
        Persistent ledger directory.
    """
    with closing(ZcodeStore(tmp_path / "state.sqlite3")) as store:
        for name in ["SessionStart", "PreToolUse", "PermissionRequest", "PostToolUseFailure"]:
            assert store.capture(hook(name)) is None
        assert store.capture(hook("Stop", turn="unstarted")) is None
        assert store.capture(hook("UserPromptSubmit", turn="unstarted")) is None
        first = store.capture(hook("UserPromptSubmit"))
        assert first is not None and first.run_sequence == 1
        assert store.capture(hook("Stop")) is not None
        for name in ["UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "PostToolUseFailure", "Stop"]:
            assert store.capture(hook(name)) is None
        next_run = store.capture(hook("UserPromptSubmit", turn="turn-2"))
        assert next_run is not None and next_run.run_sequence == 2
        assert next_run.conversation_title == first.title


def test_session_and_utf8_labels_are_independent_of_execution_identity(tmp_path: Path) -> None:
    """Equal turn labels and IDs in different sessions cannot collide in the host.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    """
    with closing(ZcodeStore(tmp_path / "state.sqlite3")) as store:
        first = store.capture(hook("UserPromptSubmit", prompt="修复接口\n" * 40, cwd="D:/项目/显示屏"))
        other = store.capture(hook("UserPromptSubmit", session="other-session"))
        assert first is not None and other is not None
        assert first.task_id != other.task_id and other.run_sequence == 1
        assert len(first.title.encode("utf-8")) <= 64 and "\n" not in first.title
        assert first.context == "显示屏"
        ended = store.capture(hook("Stop", last_assistant_message="完成\n" * 100))
        assert ended is not None and len(ended.detail.encode("utf-8")) <= 160
        assert ended.title == first.title and "\n" not in ended.detail


def test_tool_failure_and_interrupt_flag_are_not_whole_turn_outcomes(tmp_path: Path) -> None:
    """Denied, failed, or interrupted tools can recover without terminal task states.

    Parameters
    ----------
    tmp_path : Path
        Persistent ledger directory.
    """
    with closing(ZcodeStore(tmp_path / "state.sqlite3")) as store:
        store.capture(hook("UserPromptSubmit"))
        store.capture(hook("PermissionRequest"))
        recovered = store.capture(hook("PostToolUseFailure", is_interrupt=True, error="PRIVATE_ERROR",
                                      tool_input={"secret": "PRIVATE_ARGUMENT"}))
        assert recovered is not None and recovered.state == TaskState.RUNNING
        assert "PRIVATE" not in recovered.model_dump_json()
        assert store.capture(hook("Stop")) is not None
    for name in ["Interrupt", "Error", "SessionEnd", "FutureEvent"]:
        assert ZcodeHook(hook_event_name=name, session_id="s").task_state() is None


def test_native_camelcase_and_compatibility_fields_are_supported() -> None:
    """Native camelCase turn IDs work with either documented callback vocabulary."""
    callback = ZcodeHook.model_validate({
        "hookEventName": "PermissionRequest", "sessionId": "s", "turnId": "t", "toolName": "Bash",
        "transcriptPath": "must-not-be-opened", "toolInput": {"private": "PRIVATE"},
    })
    assert callback.task_state() == TaskState.WAITING_INPUT
    assert callback.detail() == "Approval requested: Bash"
    assert "PRIVATE" not in callback.model_dump_json()
    assert hook("Stop", last_assistant_message="").detail() == "Turn ended"


def test_parallel_duplicate_starts_allocate_only_one_execution(tmp_path: Path) -> None:
    """Independent hook processes cannot double-allocate a native turn.

    Parameters
    ----------
    tmp_path : Path
        Shared ledger directory.
    """
    path = tmp_path / "state.sqlite3"

    def capture(index: int) -> bool:
        """Capture the same event on an independent connection.

        Parameters
        ----------
        index : int
            Worker index, unused for the identical event.

        Returns
        -------
        bool
            Whether this worker allocated the execution.
        """
        with closing(ZcodeStore(path)) as store:
            return store.capture(hook("UserPromptSubmit")) is not None

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sum(executor.map(capture, range(6))) == 1


def test_lost_ack_retry_and_three_producers_keep_independent_cards(tmp_path: Path) -> None:
    """An accepted event retries byte-for-byte without changing its card revision.

    Parameters
    ----------
    tmp_path : Path
        State file shared intentionally by all three producers.
    """
    path = tmp_path / "shared.sqlite3"
    with closing(CodexStore(path)) as codex:
        codex.capture(CodexHook(hook_event_name="UserPromptSubmit", session_id="s", turn_id="t"))
    with closing(AgyStore(path)) as agy:
        agy.capture(AgyHook(event="PreInvocation", conversationId="s", lastUserInput="p",
                            invocationNum=0, initialNumSteps=1))
    with closing(ZcodeStore(path)) as zcode:
        zcode.capture(hook("UserPromptSubmit", session="s", turn="t"))
    bodies: list[bytes] = []
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as api:
        def forward(request: httpx.Request) -> httpx.Response:
            """Lose one acknowledgment after the real API has admitted the event.

            Parameters
            ----------
            request : httpx.Request
                Saved task event.

            Returns
            -------
            httpx.Response
                Common API acknowledgment after the initial lost response.

            Raises
            ------
            httpx.ReadTimeout
                After the first successful admission.
            """
            bodies.append(request.content)
            response = api.post("/v1/task-events", content=request.content,
                                headers={"Content-Type": "application/json"})
            if len(bodies) == 1:
                raise httpx.ReadTimeout("Acknowledgment lost", request=request)
            return response

        with (closing(ZcodeStore(path)) as store,
              httpx.Client(transport=httpx.MockTransport(forward)) as client,
              pytest.raises(httpx.ReadTimeout)):
            flush_pending(store, client, "http://127.0.0.1:8765")
        with closing(ZcodeStore(path)) as store, httpx.Client(transport=httpx.MockTransport(forward)) as client:
            flush_pending(store, client, "http://127.0.0.1:8765")
            assert store.next_pending() is None
        assert bodies[0] == bodies[1]
        records = api.get("/v1/tasks").json()
        assert len(records) == 3 and {r["source"] for r in records} == {"codex", "agy", "zcode"}
        assert all(r["revision"] == 1 for r in records)


def test_cli_offline_utf8_then_flush(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The ZCode command retains offline events and never emits a policy decision.

    Parameters
    ----------
    tmp_path : Path
        Persistent ledger directory.
    capsys : pytest.CaptureFixture[str]
        Captured hook output.
    """
    path = tmp_path / "state.sqlite3"

    def offline(request: httpx.Request) -> httpx.Response:
        """Simulate an unavailable host.

        Parameters
        ----------
        request : httpx.Request
            Queued native submission.

        Raises
        ------
        httpx.ConnectError
            Always, leaving the payload queued.
        """
        raise httpx.ConnectError("offline", request=request)

    payload = hook("UserPromptSubmit", prompt="修复中文接口").model_dump_json().encode("utf-8")
    with io.TextIOWrapper(io.BytesIO(payload)) as stdin:
        client = httpx.Client(transport=httpx.MockTransport(offline))
        with patch.object(sys, "stdin", stdin), patch("info_tv_service.hooks.cli.httpx.Client", return_value=client):
            main(["zcode", "--state-file", str(path)])
    output = capsys.readouterr()
    assert output.out == "{}\n" and "offline" in output.err
    with closing(ZcodeStore(path)) as store:
        pending = store.next_pending()
        assert pending is not None
        assert TaskEventRequest.model_validate_json(pending[1]).title == "修复中文接口"
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202, json={"outcome": "accepted"})))
    with patch("info_tv_service.hooks.cli.httpx.Client", return_value=client):
        main(["zcode", "--flush", "--state-file", str(path)])
    assert capsys.readouterr().out == "{}\n"
    with closing(ZcodeStore(path)) as store:
        assert store.next_pending() is None


@pytest.mark.parametrize("payload", [
    b"invalid", b"[]", b"{}",
    b'{"hook_event_name":"UserPromptSubmit","session_id":"s"}',
    b'{"hook_event_name":"Stop","session_id":"s","turnId":true}',
    b'{"hook_event_name":"Stop","session_id":" ","turnId":"t"}',
    b'{"hook_event_name":"Stop","session_id":"s","turnId":"t\\n"}',
    json.dumps({"hookEventName": "Stop", "sessionId": "s", "turnId": "t" * 65}).encode(),
])
def test_invalid_input_fails_open_before_creating_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: bytes,
) -> None:
    """Malformed native callbacks cannot create a task or block the agent.

    Parameters
    ----------
    tmp_path : Path
        Private state directory.
    capsys : pytest.CaptureFixture[str]
        Captured hook output.
    payload : bytes
        Invalid callback input.
    """
    path = tmp_path / "state.sqlite3"
    with io.TextIOWrapper(io.BytesIO(payload)) as stdin, patch.object(sys, "stdin", stdin):
        main(["zcode", "--state-file", str(path)])
    output = capsys.readouterr()
    assert output.out == "{}\n" and "info-tv-hook:" in output.err
    assert not path.exists()


def test_default_ledger_is_separate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal installations do not mix ZCode delivery retries with another agent.

    Parameters
    ----------
    tmp_path : Path
        Substitute local application data directory.
    monkeypatch : pytest.MonkeyPatch
        Scoped environment overrides.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_state_path("zcode") == tmp_path / "info_tv/zcode-hooks.sqlite3"
