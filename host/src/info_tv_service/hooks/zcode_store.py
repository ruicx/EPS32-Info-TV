"""Persist native ZCode turn identities and immutable delivery retries."""

from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from info_tv_service.api.models import TaskEventRequest
from info_tv_service.hooks.outbox import HookOutbox
from info_tv_service.hooks.zcode import ZcodeHook
from info_tv_service.tasks.models import TaskIcon, TaskState


class ZcodeStore(HookOutbox):
    """Keep ZCode execution ordering separate from other producers' ledgers."""

    def __init__(self, path: Path) -> None:
        """Open the outbox and initialize the native execution table.

        Parameters
        ----------
        path : Path
            Persistent ledger shared by callback processes.

        Raises
        ------
        OSError
            If the parent directory cannot be created.
        sqlite3.Error
            If the database cannot be opened or initialized.
        """
        super().__init__(path)
        self.database.execute("""
            CREATE TABLE IF NOT EXISTS zcode_runs (
                session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                run_sequence INTEGER NOT NULL, sequence INTEGER NOT NULL,
                title TEXT NOT NULL, conversation_title TEXT NOT NULL,
                context TEXT NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY (session_id, turn_id)
            )
        """)

    def capture(self, hook: ZcodeHook) -> TaskEventRequest | None:
        """Atomically order a state transition and queue its exact retry payload.

        Parameters
        ----------
        hook : ZcodeHook
            Validated native callback.

        Returns
        -------
        TaskEventRequest or None
            Queued transition, or None for unsupported, duplicate, closed, or
            unstarted activity. An unknown Stop leaves a terminal tombstone.

        Raises
        ------
        sqlite3.Error
            If the transaction cannot complete.
        ValueError
            If the generated event violates the common task contract.

        Notes
        -----
        Synchronous native callbacks establish first-observed turn ordering.
        Prompt text is a label and never participates in execution identity.
        """
        state = hook.task_state()
        if state is None:
            return None
        with self.database:
            self.database.execute("BEGIN IMMEDIATE")
            run = self.database.execute(
                "SELECT * FROM zcode_runs WHERE session_id = ? AND turn_id = ?",
                (hook.session_id, hook.turn_id),
            ).fetchone()
            if run is None:
                if hook.hook_event_name != "UserPromptSubmit":
                    if state == TaskState.COMPLETED:
                        self.database.execute(
                            "INSERT INTO zcode_runs VALUES (?, ?, 0, 0, '', '', '', ?)",
                            (hook.session_id, hook.turn_id, state),
                        )
                    return None
                ordinal = self.database.execute(
                    "SELECT COALESCE(MAX(run_sequence), 0) + 1 FROM zcode_runs WHERE session_id = ?",
                    (hook.session_id,),
                ).fetchone()[0]
                title, context = hook.labels()
                first = self.database.execute(
                    "SELECT conversation_title FROM zcode_runs WHERE session_id = ? AND run_sequence > 0 "
                    "ORDER BY run_sequence LIMIT 1", (hook.session_id,),
                ).fetchone()
                self.database.execute(
                    "INSERT INTO zcode_runs VALUES (?, ?, ?, 0, ?, ?, ?, '')",
                    (hook.session_id, hook.turn_id, ordinal, title, first[0] if first else title, context),
                )
                run = self.database.execute(
                    "SELECT * FROM zcode_runs WHERE session_id = ? AND turn_id = ?",
                    (hook.session_id, hook.turn_id),
                ).fetchone()
            elif (hook.hook_event_name == "UserPromptSubmit"
                  or run["state"] == TaskState.COMPLETED or run["state"] == state):
                return None
            submission = TaskEventRequest(
                event_id=uuid4(), source="zcode",
                task_id=uuid5(NAMESPACE_URL, f"info-tv:zcode:{hook.session_id}:{hook.turn_id}").hex,
                conversation_id=hook.session_id, run_sequence=run["run_sequence"],
                sequence=run["sequence"] + 1, state=state, title=run["title"],
                conversation_title=run["conversation_title"], context=run["context"],
                detail=hook.detail(), icon=TaskIcon.CODE,
            )
            self.database.execute(
                "UPDATE zcode_runs SET sequence = ?, state = ? WHERE session_id = ? AND turn_id = ?",
                (submission.sequence, state, hook.session_id, hook.turn_id),
            )
            self.enqueue(submission)
            return submission
