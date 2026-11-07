"""Persist immutable hook submissions until the host acknowledges delivery."""

import sqlite3
from pathlib import Path

from info_tv_service.api.models import TaskEventRequest


class HookOutbox:
    """Own one process's connection to a shared SQLite delivery queue."""

    def __init__(self, path: Path) -> None:
        """Open the queue, creating its parent directory and schema if needed.

        Parameters
        ----------
        path : Path
            Persistent state file shared by callback processes.

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
        self.database.execute("""
            CREATE TABLE IF NOT EXISTS outbox (
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
            )
        """)

    def close(self) -> None:
        """Release this process's database handle."""
        self.database.close()

    def enqueue(self, submission: TaskEventRequest) -> None:
        """Save a submission inside the caller's state transition transaction.

        Parameters
        ----------
        submission : TaskEventRequest
            Validated event whose UUID and body must remain unchanged on retry.
        """
        self.database.execute(
            "INSERT INTO outbox (event_id, payload) VALUES (?, ?)",
            (submission.event_id.hex, submission.model_dump_json(exclude_none=True)),
        )

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
