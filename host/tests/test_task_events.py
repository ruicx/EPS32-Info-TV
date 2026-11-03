"""Business-ordering and bounded-admission regression tests."""

from dataclasses import replace
from uuid import uuid4

import pytest

from info_tv_service.tasks.models import TaskEvent, TaskState
from info_tv_service.tasks.store import AdmissionError, TaskStore


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
    """An unadmitted fifth task cannot alter the four accepted tasks."""
    store = TaskStore()
    for index in range(4):
        store.commit(store.prepare(event(task_id=str(index))))
    before = store.list_tasks()
    with pytest.raises(AdmissionError, match="capacity"):
        store.prepare(event(task_id="fifth"))
    assert store.list_tasks() == before
