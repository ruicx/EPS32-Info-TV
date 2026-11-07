"""Replay native agy callbacks through persistent identity and HTTP delivery."""

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
from info_tv_service.tasks.models import TaskState


def hook(name: str, **changes: object) -> AgyHook:
    """Reuse real native fields with explicit test overrides.

    Parameters
    ----------
    name : str
        Event name configured on the hook command line.
    **changes : object
        Native camelCase payload fields to replace.

    Returns
    -------
    AgyHook
        Validated callback built from the recorded probe.
    """
    evidence = Path(__file__).resolve().parents[2] / "docs/evidence/agy-hooks-2026-11-07.json"
    samples = json.loads(evidence.read_text(encoding="utf-8"))["representative_captures"]
    return AgyHook.model_validate(samples[name]["payload"] | {"event": name} | changes)


def test_native_timeline_keeps_model_cycles_in_one_run(tmp_path: Path) -> None:
    """Restarted callback processes retain one card per conversation and turn.

    Parameters
    ----------
    tmp_path : Path
        Private SQLite state directory.
    """
    evidence = Path(__file__).resolve().parents[2] / "docs/evidence/agy-hooks-2026-11-07.json"
    timeline = json.loads(evidence.read_text(encoding="utf-8"))["timeline"]
    session = "e201342c-823d-4eb8-bc12-440c43964ed2"
    submissions = []
    for sample in timeline:
        if sample["conversationId"] != session or sample["event"] not in ("PreInvocation", "Stop"):
            continue
        with closing(AgyStore(tmp_path / "state.sqlite3")) as store:
            submission = store.capture(hook(sample["event"], **sample))
            if submission is not None:
                submissions.append(submission)
    ids = [s.task_id for s in submissions]
    assert ids[0] == ids[1] and ids[2] == ids[3] and len(set(ids)) == 3
    assert [s.run_sequence for s in submissions] == [1, 1, 2, 2, 3]
    assert [s.sequence for s in submissions] == [1, 2, 1, 2, 1]
    assert [s.state for s in submissions] == [TaskState.RUNNING, TaskState.COMPLETED,
                                            TaskState.RUNNING, TaskState.COMPLETED, TaskState.RUNNING]
    assert all(s.source == "agy" and s.progress_percent is None for s in submissions)


def test_repeated_prompts_use_step_identity_and_keep_utf8_labels(tmp_path: Path) -> None:
    """Equal prompts are distinct executions while old starts cannot revive them.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    """
    prompt = "修复显示接口\n" * 40
    with closing(AgyStore(tmp_path / "state.sqlite3")) as store:
        first = store.capture(hook("PreInvocation", lastUserInput=prompt, workspacePaths=["D:/项目/显示屏"]))
        assert first is not None and first.context == "显示屏"
        assert len(first.title.encode("utf-8")) <= 64 and "\n" not in first.title
        ended = store.capture(hook("Stop", lastUserInput=prompt))
        assert ended is not None and ended.state == TaskState.COMPLETED
        assert store.capture(hook("Stop", lastUserInput=prompt)) is None
        assert store.capture(hook("PreInvocation", lastUserInput=prompt)) is None
        second = store.capture(hook("PreInvocation", initialNumSteps=5, lastUserInput=prompt))
        assert second is not None and second.task_id != first.task_id and second.run_sequence == 2
        third = store.capture(hook("PreInvocation", initialNumSteps=9, lastUserInput="Different prompt"))
        assert third is not None and third.run_sequence == 3 and third.conversation_title == first.title
        assert store.capture(hook("Stop", lastUserInput=prompt)) is None
        assert store.capture(hook("PreInvocation", initialNumSteps=5, lastUserInput=prompt)) is None
        assert store.capture(hook("Stop", lastUserInput="Different prompt")) is not None


@pytest.mark.parametrize("reason,state", [
    ("ERROR", TaskState.FAILED), ("MAX_INVOCATIONS", TaskState.FAILED),
    ("MAX_FORCED_INVOCATIONS", TaskState.FAILED), ("MAX_TOKEN_BUDGET_EXCEEDED", TaskState.FAILED),
    ("USER_CANCELED", TaskState.INTERRUPTED),
])
def test_documented_stop_contract_is_terminal(tmp_path: Path, reason: str, state: TaskState) -> None:
    """Cover documented reasons separately from live-observed normal completion.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    reason : str
        Documented stop reason, not captured in the real probe.
    state : TaskState
        Expected task state.
    """
    with closing(AgyStore(tmp_path / "state.sqlite3")) as store:
        store.capture(hook("PreInvocation"))
        terminal = store.capture(hook("Stop", terminationReason=reason, error="Private failure text"))
        assert terminal is not None and terminal.state == state and terminal.sequence == 2
        assert "Private" not in terminal.model_dump_json()
        assert store.capture(hook("Stop")) is None
        assert store.capture(hook("PreInvocation")) is None


def test_unsupported_and_unmatched_callbacks_do_not_invent_outcomes(tmp_path: Path) -> None:
    """Unknown stops and missing starts cannot be interpreted as task success.

    Parameters
    ----------
    tmp_path : Path
        Private ledger directory.
    """
    with closing(AgyStore(tmp_path / "state.sqlite3")) as store:
        assert store.capture(hook("Stop")) is None
        assert store.capture(hook("PreInvocation", invocationNum=1)) is None
        assert store.next_pending() is None
        first = store.capture(hook("PreInvocation"))
        assert first is not None
        for changes in [{"fullyIdle": False}, {"terminationReason": "FUTURE_REASON"},
                        {"terminationReason": "TERMINAL_STEP_TYPE"}, {"lastUserInput": "Other prompt"}]:
            assert store.capture(hook("Stop", **changes)) is None
        terminal = store.capture(hook("Stop"))
        assert terminal is not None and terminal.sequence == 2


def test_parallel_duplicate_starts_queue_once(tmp_path: Path) -> None:
    """Concurrent callback processes cannot double-allocate an observed start.

    Parameters
    ----------
    tmp_path : Path
        Shared SQLite ledger directory.
    """
    path = tmp_path / "state.sqlite3"

    def capture(index: int) -> bool:
        """Capture the same source callback on an independent connection.

        Parameters
        ----------
        index : int
            Worker index, unused because source callbacks are identical.

        Returns
        -------
        bool
            Whether this worker created the start event.
        """
        with closing(AgyStore(path)) as store:
            return store.capture(hook("PreInvocation")) is not None

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sum(executor.map(capture, range(6))) == 1
    with closing(AgyStore(path)) as store:
        pending = store.next_pending()
        assert pending is not None
        store.acknowledge(pending[0])
        assert store.next_pending() is None


def test_retry_and_shared_state_keep_producer_cards_independent(tmp_path: Path) -> None:
    """Lost acknowledgments retry unchanged and agy cannot replace a Codex card.

    Parameters
    ----------
    tmp_path : Path
        Shared state file directory.
    """
    path = tmp_path / "shared.sqlite3"
    with closing(CodexStore(path)) as store:
        store.capture(CodexHook(hook_event_name="UserPromptSubmit", session_id="same-session", turn_id="turn-1"))
    with closing(AgyStore(path)) as store:
        store.capture(hook("PreInvocation", conversationId="same-session"))
        store.capture(hook("PreInvocation", conversationId="another-session"))
    bodies: list[bytes] = []
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as api:
        def forward(request: httpx.Request) -> httpx.Response:
            """Lose the first acknowledgment only after the host has admitted it.

            Parameters
            ----------
            request : httpx.Request
                Queued native adapter submission.

            Returns
            -------
            httpx.Response
                Actual task API response after the first attempt.

            Raises
            ------
            httpx.ReadTimeout
                After accepting the first event.
            """
            bodies.append(request.content)
            response = api.post("/v1/task-events", content=request.content,
                                headers={"Content-Type": "application/json"})
            if len(bodies) == 1:
                raise httpx.ReadTimeout("Acknowledgment lost", request=request)
            return response

        with (closing(AgyStore(path)) as store,
              httpx.Client(transport=httpx.MockTransport(forward)) as client,
              pytest.raises(httpx.ReadTimeout)):
            flush_pending(store, client, "http://127.0.0.1:8765")
        with closing(AgyStore(path)) as store, httpx.Client(transport=httpx.MockTransport(forward)) as client:
            flush_pending(store, client, "http://127.0.0.1:8765")
            assert store.next_pending() is None
        assert bodies[0] == bodies[1]
        records = api.get("/v1/tasks").json()
        assert len(records) == 3 and {r["source"] for r in records} == {"codex", "agy"}
        assert all(r["revision"] == 1 for r in records)


def test_cli_event_argument_utf8_and_offline_retry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Configured event names override input metadata and forwarding stays neutral.

    Parameters
    ----------
    tmp_path : Path
        Private queue directory.
    capsys : pytest.CaptureFixture[str]
        Captured hook output.
    """
    path = tmp_path / "state.sqlite3"
    native = hook("PreInvocation", lastUserInput="修复中文接口").model_dump(by_alias=True) | {"event": "Stop"}

    def offline(request: httpx.Request) -> httpx.Response:
        """Leave the event queued while the local host is unavailable.

        Parameters
        ----------
        request : httpx.Request
            Sender request.

        Raises
        ------
        httpx.ConnectError
            Always, simulating an offline host.
        """
        raise httpx.ConnectError("offline", request=request)

    with io.TextIOWrapper(io.BytesIO(json.dumps(native, ensure_ascii=False).encode("utf-8"))) as stdin:
        client = httpx.Client(transport=httpx.MockTransport(offline))
        with patch.object(sys, "stdin", stdin), patch("info_tv_service.hooks.cli.httpx.Client", return_value=client):
            main(["agy", "PreInvocation", "--state-file", str(path)])
    output = capsys.readouterr()
    assert output.out == "{}\n" and "offline" in output.err
    with closing(AgyStore(path)) as store:
        pending = store.next_pending()
        assert pending is not None
        submission = TaskEventRequest.model_validate_json(pending[1])
        assert submission.source == "agy" and submission.title == "修复中文接口"
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202, json={"outcome": "accepted"})))
    with patch("info_tv_service.hooks.cli.httpx.Client", return_value=client):
        main(["agy", "--flush", "--state-file", str(path)])
    assert capsys.readouterr().out == "{}\n"
    with closing(AgyStore(path)) as store:
        assert store.next_pending() is None


@pytest.mark.parametrize("event,payload", [
    (None, b"{}"), ("PreInvocation", b"[]"), ("PreInvocation", b"invalid"),
    ("PreInvocation", b'{"conversationId":"c","lastUserInput":"p"}'),
    ("PreInvocation", b'{"conversationId":"c","lastUserInput":"p","invocationNum":0,"initialNumSteps":true}'),
    ("Stop", b'{"conversationId":"c","lastUserInput":"p","terminationReason":"NO_TOOL_CALL"}'),
])
def test_invalid_input_is_neutral_without_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], event: str | None, payload: bytes,
) -> None:
    """Missing event names and invalid native fields cannot create task cards.

    Parameters
    ----------
    tmp_path : Path
        Private state directory.
    capsys : pytest.CaptureFixture[str]
        Hook output capture.
    event : str or None
        Command-line event name, when supplied.
    payload : bytes
        Invalid native callback input.
    """
    path = tmp_path / "state.sqlite3"
    argv = ["agy", *([event] if event else []), "--state-file", str(path)]
    with io.TextIOWrapper(io.BytesIO(payload)) as stdin, patch.object(sys, "stdin", stdin):
        main(argv)
    output = capsys.readouterr()
    assert output.out == "{}\n" and "info-tv-hook:" in output.err
    assert not path.exists()


def test_default_ledgers_are_separate_per_producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal installations do not accidentally mix producer retry queues.

    Parameters
    ----------
    tmp_path : Path
        Substitute local application data directory.
    monkeypatch : pytest.MonkeyPatch
        Scoped environment overrides.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_state_path() == tmp_path / "info_tv/codex-hooks.sqlite3"
    assert default_state_path("agy") == tmp_path / "info_tv/agy-hooks.sqlite3"
