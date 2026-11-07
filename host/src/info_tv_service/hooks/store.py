"""Persist Codex run ordering and immutable HTTP retry payloads in SQLite."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from info_tv_service.api.models import TaskEventRequest
from info_tv_service.hooks.codex import CodexHook
from info_tv_service.tasks.models import TaskIcon, TaskState


class CodexStore:
    """Own one process's connection to the shared hook ledger and outbox."""

    def __init__(self, path: Path) -> None:
        """Open the ledger, creating its parent directory and schema if needed.

        Parameters
        ----------
        path : Path
            Persistent state file shared by callbacks for this installation.

        Raises
        ------
        OSError
            If the parent directory cannot be created.
        sqlite3.Error
            If the state file cannot be opened or initialized.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database = sqlite3.connect(path, timeout=1)
        self.database.row_factory = sqlite3.Row
        self.database.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                run_sequence INTEGER NOT NULL, sequence INTEGER NOT NULL,
                title TEXT NOT NULL, conversation_title TEXT NOT NULL,
                context TEXT NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY (session_id, turn_id)
            );
            CREATE TABLE IF NOT EXISTS outbox (
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        """Release this process's database handle."""
        self.database.close()

    def capture(self, hook: CodexHook) -> TaskEventRequest | None:
        """Atomically order a transition and retain its exact retry payload.

        Parameters
        ----------
        hook : CodexHook
            Validated native callback.

        Returns
        -------
        TaskEventRequest or None
            Queued transition, or None for a duplicate, unsupported event, or
            activity without a known start. Unknown terminal events leave a
            tombstone without advancing the conversation ordinal.

        Raises
        ------
        sqlite3.Error
            If the transaction cannot be completed.
        ValueError
            If the generated submission violates the host contract.
        """
        state = hook.task_state()
        if state is None:
            return None
        with self.database:
            self.database.execute("BEGIN IMMEDIATE")
            run = self.database.execute(
                "SELECT * FROM runs WHERE session_id = ? AND turn_id = ?",
                (hook.session_id, hook.turn_id),
            ).fetchone()
            if run is None:
                if hook.hook_event_name != "UserPromptSubmit":
                    if state in (TaskState.COMPLETED, TaskState.INTERRUPTED):
                        self.database.execute(
                            "INSERT INTO runs VALUES (?, ?, 0, 0, '', '', '', ?)",
                            (hook.session_id, hook.turn_id, state),
                        )
                    return None
                ordinal = self.database.execute(
                    "SELECT COALESCE(MAX(run_sequence), 0) + 1 FROM runs WHERE session_id = ?",
                    (hook.session_id,),
                ).fetchone()[0]
                title, context = hook.labels()
                first = self.database.execute(
                    "SELECT conversation_title FROM runs WHERE session_id = ? AND run_sequence > 0 "
                    "ORDER BY run_sequence LIMIT 1", (hook.session_id,),
                ).fetchone()
                self.database.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, 0, ?, ?, ?, '')",
                    (hook.session_id, hook.turn_id, ordinal, title, first[0] if first else title, context),
                )
                run = self.database.execute(
                    "SELECT * FROM runs WHERE session_id = ? AND turn_id = ?",
                    (hook.session_id, hook.turn_id),
                ).fetchone()
            elif (hook.hook_event_name == "UserPromptSubmit"
                  or run["state"] in (TaskState.COMPLETED, TaskState.INTERRUPTED) or run["state"] == state):
                return None
            submission = TaskEventRequest(
                event_id=uuid4(), source="codex", task_id=str(hook.turn_id),
                conversation_id=hook.session_id, run_sequence=run["run_sequence"],
                sequence=run["sequence"] + 1, state=state, title=run["title"],
                conversation_title=run["conversation_title"], context=run["context"],
                detail=hook.detail(), icon=TaskIcon.CODE,
            )
            self.database.execute(
                "UPDATE runs SET sequence = ?, state = ? WHERE session_id = ? AND turn_id = ?",
                (submission.sequence, state, hook.session_id, hook.turn_id),
            )
            self.database.execute(
                "INSERT INTO outbox (event_id, payload) VALUES (?, ?)",
                (submission.event_id.hex, submission.model_dump_json(exclude_none=True)),
            )
            return submission

    def next_pending(self) -> tuple[str, str] | None:
        """Read the oldest unacknowledged event without holding a write lock.

        Returns
        -------
        tuple[str, str] or None
            Event UUID hex and JSON body, or None for an empty queue.
        """
        row = self.database.execute(
            "SELECT event_id, payload FROM outbox ORDER BY position LIMIT 1",
        ).fetchone()
        return (row["event_id"], row["payload"]) if row else None

    def acknowledge(self, event_id: str) -> None:
        """Remove a delivered event; concurrent acknowledgments are harmless.

        Parameters
        ----------
        event_id : str
            UUID of the exact event accepted by the host.
        """
        with self.database:
            self.database.execute("DELETE FROM outbox WHERE event_id = ?", (event_id,))
