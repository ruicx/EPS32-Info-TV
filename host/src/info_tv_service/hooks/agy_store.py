"""Correlate sequential agy starts and stops with a persistent conversation cursor."""

from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from info_tv_service.api.models import TaskEventRequest
from info_tv_service.hooks.agy import AgyHook
from info_tv_service.hooks.outbox import HookOutbox
from info_tv_service.tasks.models import TaskIcon, TaskState


class AgyStore(HookOutbox):
    """Keep one current execution per conversation and an immutable retry queue."""

    def __init__(self, path: Path) -> None:
        """Open the queue and initialize the agy conversation cursor table.

        Parameters
        ----------
        path : Path
            Persistent state file shared by callback processes.

        Raises
        ------
        OSError
            If the parent directory cannot be created.
        sqlite3.Error
            If the database cannot be opened or initialized.
        """
        super().__init__(path)
        self.database.execute("""
            CREATE TABLE IF NOT EXISTS agy_conversations (
                conversation_id TEXT PRIMARY KEY, start_step INTEGER NOT NULL,
                run_sequence INTEGER NOT NULL, sequence INTEGER NOT NULL,
                title TEXT NOT NULL, conversation_title TEXT NOT NULL,
                context TEXT NOT NULL, state TEXT NOT NULL, prompt_hash TEXT NOT NULL
            )
        """)

    def capture(self, hook: AgyHook) -> TaskEventRequest | None:
        """Atomically correlate a native callback and queue its task transition.

        Parameters
        ----------
        hook : AgyHook
            Validated invocation or stop callback.

        Returns
        -------
        TaskEventRequest or None
            Queued transition, or None for duplicate/older starts, unsupported
            outcomes, and stops without a matching current running prompt.

        Raises
        ------
        sqlite3.Error
            If the transaction cannot be completed.
        ValueError
            If a generated task submission violates the host contract.

        Notes
        -----
        Stop has no native turn ID. A prompt digest rejects mismatched stops but
        cannot distinguish a late stop when two turns have identical prompts.
        Native callbacks must remain synchronous and sequential per conversation.
        """
        state = hook.task_state()
        if state is None:
            return None
        prompt_hash = sha256(hook.last_user_input.encode("utf-8")).hexdigest()
        with self.database:
            self.database.execute("BEGIN IMMEDIATE")
            run = self.database.execute(
                "SELECT * FROM agy_conversations WHERE conversation_id = ?", (hook.conversation_id,),
            ).fetchone()
            if hook.event == "PreInvocation":
                assert hook.initial_num_steps is not None
                if run is not None and hook.initial_num_steps <= run["start_step"]:
                    return None
                title, context = hook.labels()
                self.database.execute(
                    "INSERT OR REPLACE INTO agy_conversations VALUES (?, ?, ?, 0, ?, ?, ?, '', ?)",
                    (hook.conversation_id, hook.initial_num_steps, run["run_sequence"] + 1 if run else 1,
                     title, run["conversation_title"] if run else title, context, prompt_hash),
                )
                run = self.database.execute(
                    "SELECT * FROM agy_conversations WHERE conversation_id = ?", (hook.conversation_id,),
                ).fetchone()
            elif run is None or run["state"] != TaskState.RUNNING or run["prompt_hash"] != prompt_hash:
                return None
            submission = TaskEventRequest(
                event_id=uuid4(), source="agy",
                task_id=uuid5(NAMESPACE_URL, f"info-tv:agy:{hook.conversation_id}:{run['start_step']}").hex,
                conversation_id=hook.conversation_id, run_sequence=run["run_sequence"],
                sequence=run["sequence"] + 1, state=state, title=run["title"],
                conversation_title=run["conversation_title"], context=run["context"],
                detail=hook.detail(), icon=TaskIcon.CODE,
            )
            self.database.execute(
                "UPDATE agy_conversations SET sequence = ?, state = ? WHERE conversation_id = ?",
                (submission.sequence, state, hook.conversation_id),
            )
            self.enqueue(submission)
            return submission
