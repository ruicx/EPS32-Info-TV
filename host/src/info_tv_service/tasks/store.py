"""Bounded in-memory task state with ordered, idempotent event admission."""

from collections import OrderedDict
from uuid import uuid4

from info_tv_service.config import EVENT_CACHE_CAPACITY, MAX_TASKS
from info_tv_service.tasks.models import TaskEvent, TaskRecord, TaskState, TaskUpdate


class AdmissionError(Exception):
    """Reject conflicting input or a full bounded store."""

    def __init__(self, detail: str, status_code: int = 409) -> None:
        """Initialize the rejection.

        Parameters
        ----------
        detail : str
            Human-readable rejection reason.
        status_code : int
            Corresponding HTTP response status.
        """
        super().__init__(detail)
        self.status_code = status_code


class TaskStore:
    """Own at most four current tasks and a bounded event identity cache."""

    def __init__(self) -> None:
        """Create empty state owned by the application event loop."""
        self._tasks: dict[tuple[str, str], TaskRecord] = {}
        self._events: OrderedDict[str, TaskEvent] = OrderedDict()

    def prepare(self, event: TaskEvent) -> TaskUpdate:
        """Evaluate an event without changing state.

        Parameters
        ----------
        event : TaskEvent
            Validated producer update.

        Returns
        -------
        TaskUpdate
            Existing or proposed task state and notification intent.

        Raises
        ------
        AdmissionError
            If identities conflict, a sequence is reused, or four tasks exist.
        """
        key = (event.source, event.task_id)
        previous = self._tasks.get(key)
        seen = self._events.get(event.event_id)
        if seen is not None:
            if seen != event:
                raise AdmissionError("event_id was reused with different content")
            assert previous is not None
            return TaskUpdate("duplicate", previous)
        if previous is not None and event.sequence <= previous.event.sequence:
            if event.sequence == previous.event.sequence and event != previous.event:
                raise AdmissionError("sequence was reused with different content")
            return TaskUpdate("stale", previous)
        if previous is None and len(self._tasks) >= MAX_TASKS:
            raise AdmissionError("Task capacity reached", 503)
        completed = previous.completion_notified if previous else False
        notify = (
            event.state == TaskState.COMPLETED and not completed
        ) or (
            event.state in (TaskState.WAITING_INPUT, TaskState.FAILED)
            and (previous is None or previous.event.state != event.state)
        )
        record = TaskRecord(
            event, previous.card_id if previous else uuid4().hex,
            previous.revision + 1 if previous else 1,
            completed or event.state == TaskState.COMPLETED,
        )
        return TaskUpdate("accepted", record, notify)

    def commit(self, update: TaskUpdate) -> None:
        """Commit an admitted update after downstream capacity checks.

        Parameters
        ----------
        update : TaskUpdate
            Accepted result returned by ``prepare`` in the same event-loop turn.
        """
        event = update.record.event
        self._tasks[event.source, event.task_id] = update.record
        self._events[event.event_id] = event
        if len(self._events) > EVENT_CACHE_CAPACITY:
            self._events.popitem(last=False)

    def list_tasks(self) -> list[TaskRecord]:
        """Return current tasks in admission order.

        Returns
        -------
        list[TaskRecord]
            Immutable task records.
        """
        return list(self._tasks.values())
