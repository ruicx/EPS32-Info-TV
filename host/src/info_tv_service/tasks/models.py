"""Immutable task events and state, independent of HTTP and Protobuf."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class TaskState(StrEnum):
    """Supported source-independent execution states."""

    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskEvent:
    """Describe one ordered task update.

    Parameters
    ----------
    event_id : str
        Globally unique UUID hex identity retained across retries.
    source : str
        Producer namespace.
    task_id : str
        Execution identity within the producer namespace.
    sequence : int
        Strictly increasing update sequence for this run.
    state : TaskState
        Current execution state.
    title : str
        Display title within 64 UTF-8 bytes.
    detail : str
        Explanation within 160 UTF-8 bytes.
    progress_percent : int or None
        Optional integer progress from zero through 100.

    Notes
    -----
    ``task_id`` identifies a run within ``source``. Retries retain every field.
    """

    event_id: str
    source: str
    task_id: str
    sequence: int
    state: TaskState
    title: str
    detail: str = ""
    progress_percent: int | None = None


@dataclass(frozen=True)
class TaskRecord:
    """Retain current content and device ordering metadata.

    Parameters
    ----------
    event : TaskEvent
        Most recent accepted producer update.
    card_id : str
        Service-assigned device identity.
    revision : int
        Device content revision within this session.
    completion_notified : bool
        Whether this run already generated its completion transition.
    """

    event: TaskEvent
    card_id: str
    revision: int
    completion_notified: bool


@dataclass(frozen=True)
class TaskUpdate:
    """Represent an evaluated update before its atomic commitment.

    Parameters
    ----------
    outcome : str
        Accepted, duplicate, or stale admission outcome.
    record : TaskRecord
        Proposed state, or current state for a duplicate/stale update.
    notify : bool
        Whether commitment requires notification admission.
    """

    outcome: Literal["accepted", "duplicate", "stale"]
    record: TaskRecord
    notify: bool = False
