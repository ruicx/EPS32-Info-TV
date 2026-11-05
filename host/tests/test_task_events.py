"""Business-ordering and bounded-admission regression tests."""

from dataclasses import replace
from uuid import uuid4

import pytest

from info_tv_service.tasks.models import TaskEvent, TaskState
from info_tv_service.tasks.store import AdmissionError, TaskStore
from info_tv_service.config import EVENT_CACHE_CAPACITY, MAX_TASKS


def event(sequence: int = 1, state: TaskState = TaskState.RUNNING, task_id: str = "task") -> TaskEvent:
    """Return a unique valid task event.

    Parameters
    ----------
    sequence : int
        Task update sequence.
    state : TaskState
        Execution state.
    task_id : str
        Source-scoped run identity.

    Returns
    -------
    TaskEvent
        Test event.
    """
    return TaskEvent(uuid4().hex, "test", task_id, sequence, state, "Build")


def test_updates_replace_one_task_and_isolate_concurrent_runs() -> None:
    """Updates replace current state while same-source runs stay independent."""
    store = TaskStore()
    first = store.prepare(event())
    store.commit(first)
    newer = store.prepare(event(2))
    store.commit(newer)
    store.commit(store.prepare(event(task_id="another")))
    assert len(store.list_tasks()) == 2
    assert newer.record.card_id == first.record.card_id
    assert newer.record.revision == first.record.revision + 1


def test_duplicate_conflict_stale_and_completion_once() -> None:
    """Retries and old progress cannot repeat completion or overwrite it."""
    store = TaskStore()
    complete = event(3, TaskState.COMPLETED)
    update = store.prepare(complete)
    assert update.notify
    store.commit(update)
    assert store.prepare(complete).outcome == "duplicate"
    assert store.prepare(event(1)).outcome == "stale"
    assert not store.prepare(event(4, TaskState.COMPLETED)).notify
    with pytest.raises(AdmissionError):
        store.prepare(replace(complete, title="Conflicting payload"))
    with pytest.raises(AdmissionError):
        store.prepare(event(3, TaskState.FAILED))
    assert store.list_tasks()[0].event == complete


def test_capacity_rejects_without_mutation() -> None:
    """An unadmitted extra task cannot alter accepted cards at capacity."""
    store = TaskStore()
    for index in range(MAX_TASKS):
        store.commit(store.prepare(event(task_id=str(index))))
    before = store.list_tasks()
    with pytest.raises(AdmissionError, match="capacity"):
        store.prepare(event(task_id="overflow"))
    assert store.list_tasks() == before


def test_conversation_reuses_card_across_runs_and_completes_each_run_once() -> None:
    """A new execution reuses its conversation card and resets completion state."""
    store = TaskStore()
    first = replace(event(state=TaskState.COMPLETED), conversation_id="thread", run_sequence=1)
    old = store.prepare(first)
    store.commit(old)
    second = replace(first, event_id=uuid4().hex, task_id="run-2", run_sequence=2,
                     state=TaskState.RUNNING)
    update = store.prepare(second)
    store.commit(update)
    assert update.record.card_id == old.record.card_id
    assert update.record.revision == 2
    assert len(store.list_tasks()) == 1
    complete = replace(second, event_id=uuid4().hex, sequence=2, state=TaskState.COMPLETED)
    update = store.prepare(complete)
    assert update.notify
    store.commit(update)
    assert store.prepare(complete).outcome == "duplicate"
    assert not store.prepare(replace(complete, event_id=uuid4().hex, sequence=3)).notify


def test_late_execution_cannot_replace_current_conversation_state() -> None:
    """An old run, including its first delayed event, cannot overwrite a newer run."""
    store = TaskStore()
    current = replace(event(task_id="new"), conversation_id="thread", run_sequence=3)
    store.commit(store.prepare(current))
    late = replace(event(100, TaskState.FAILED, "old"), conversation_id="thread", run_sequence=2)
    assert store.prepare(late).outcome == "stale"
    assert store.list_tasks()[0].event == current
    with pytest.raises(AdmissionError, match="ordinal"):
        store.prepare(replace(late, event_id=uuid4().hex, run_sequence=3))
    with pytest.raises(AdmissionError, match="ordinal"):
        store.prepare(replace(current, event_id=uuid4().hex, run_sequence=4))


def test_sources_conversations_and_legacy_tasks_have_separate_identities() -> None:
    """Same titles, IDs, and projects do not merge unrelated conversations."""
    store = TaskStore()
    first = replace(event(), source="codex", conversation_id="same", run_sequence=1)
    for submission in (first, replace(first, event_id=uuid4().hex, source="agy"),
                       replace(first, event_id=uuid4().hex, task_id="other", conversation_id="other"),
                       replace(event(task_id="same"), source="codex")):
        store.commit(store.prepare(submission))
    assert len({record.card_id for record in store.list_tasks()}) == 4


def test_execution_identity_cannot_move_to_another_conversation() -> None:
    """Reusing a source-scoped task ID with a new conversation is a conflict."""
    store = TaskStore()
    first = replace(event(), conversation_id="thread", run_sequence=1)
    store.commit(store.prepare(first))
    with pytest.raises(AdmissionError, match="cannot move"):
        store.prepare(replace(first, event_id=uuid4().hex, conversation_id="other"))
    # Current identities remain protected after their event-cache entries expire.
    other = replace(event(task_id="busy"), conversation_id="busy-thread", run_sequence=1)
    for sequence in range(1, EVENT_CACHE_CAPACITY + 2):
        store.commit(store.prepare(replace(other, event_id=uuid4().hex, sequence=sequence)))
    with pytest.raises(AdmissionError, match="cannot move"):
        store.prepare(replace(first, event_id=uuid4().hex, conversation_id="other"))
