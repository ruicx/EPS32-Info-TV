"""Interpret Codex command-hook input without reading private transcripts."""

from pathlib import PureWindowsPath

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from info_tv_service.tasks.models import TaskState


def display_text(value: str, byte_limit: int) -> str:
    """Collapse controls and truncate text at a UTF-8 character boundary.

    Parameters
    ----------
    value : str
        Agent-supplied display text.
    byte_limit : int
        Maximum encoded field size.

    Returns
    -------
    str
        Printable single-line text within the byte limit.
    """
    printable = "".join(character if character.isprintable() else " " for character in value)
    return " ".join(printable.split()).encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore").strip()


class CodexHook(BaseModel):
    """Read the supported public callback fields and ignore additional metadata."""

    model_config = ConfigDict(extra="ignore", strict=True)
    hook_event_name: str
    session_id: str
    turn_id: str | None = None
    prompt: str = ""
    cwd: str = ""
    tool_name: str = ""
    last_assistant_message: str | None = None

    @field_validator("session_id", "turn_id")
    @classmethod
    def validate_identity(cls, value: str | None) -> str | None:
        """Keep opaque identities unchanged and within the host contract.

        Parameters
        ----------
        value : str or None
            Source-provided session or turn identity.

        Returns
        -------
        str or None
            Unchanged valid identity.

        Raises
        ------
        ValueError
            If an identity is blank, contains controls, or exceeds 64 bytes.
        """
        if value is not None and (not value.strip() or not value.isprintable()
                                  or len(value.encode("utf-8")) > 64):
            raise ValueError("Codex identities must be printable, nonblank, and at most 64 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def validate_turn(self) -> "CodexHook":
        """Require an execution identity for callbacks that change task state.

        Returns
        -------
        CodexHook
            Validated callback.

        Raises
        ------
        ValueError
            If a supported turn callback lacks its turn identity.
        """
        if self.task_state() is not None and self.turn_id is None:
            raise ValueError("A supported Codex turn callback requires turn_id")
        return self

    def task_state(self) -> TaskState | None:
        """Select a task state without inferring success from agent output.

        Returns
        -------
        TaskState or None
            Mapped state, or None for an unsupported/lifecycle-only event.
        """
        return {
            "UserPromptSubmit": TaskState.RUNNING,
            "PreToolUse": TaskState.RUNNING,
            "PostToolUse": TaskState.RUNNING,
            "PermissionRequest": TaskState.WAITING_INPUT,
            "Stop": TaskState.COMPLETED,
            "Interrupt": TaskState.INTERRUPTED,
        }.get(self.hook_event_name)

    def labels(self) -> tuple[str, str]:
        """Derive bounded task and workspace labels independently of identity.

        Returns
        -------
        tuple[str, str]
            Initial prompt title and workspace basename.
        """
        return (display_text(self.prompt, 64) or "Codex task",
                display_text(PureWindowsPath(self.cwd).name, 64))

    def detail(self) -> str:
        """Describe a transition without exposing tool arguments or output.

        Returns
        -------
        str
            Display detail within 160 UTF-8 bytes.
        """
        if self.hook_event_name == "PermissionRequest":
            return display_text(f"Approval requested: {self.tool_name or 'tool'}", 160)
        if self.hook_event_name == "Stop":
            return display_text(self.last_assistant_message or "Turn ended", 160)
        if self.hook_event_name == "Interrupt":
            return "Turn interrupted"
        return "Working"
