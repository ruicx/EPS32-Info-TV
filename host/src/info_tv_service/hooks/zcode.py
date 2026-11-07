"""Interpret ZCode's native callbacks without opening temporary transcripts."""

from pathlib import PureWindowsPath

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from info_tv_service.hooks.text import display_text
from info_tv_service.tasks.models import TaskState


class ZcodeHook(BaseModel):
    """Read native identities and display fields, ignoring tool inputs and output."""

    model_config = ConfigDict(extra="ignore", strict=True)
    hook_event_name: str = Field(validation_alias=AliasChoices("hook_event_name", "hookEventName"))
    session_id: str = Field(validation_alias=AliasChoices("session_id", "sessionId"))
    turn_id: str | None = Field(default=None, validation_alias=AliasChoices("turnId", "turn_id"))
    prompt: str = ""
    cwd: str = ""
    tool_name: str = Field(default="", validation_alias=AliasChoices("tool_name", "toolName"))
    last_assistant_message: str = Field(
        default="", validation_alias=AliasChoices("last_assistant_message", "responseText"),
    )

    @field_validator("session_id", "turn_id")
    @classmethod
    def validate_identity(cls, value: str | None) -> str | None:
        """Preserve opaque identities within the common task API's bounds.

        Parameters
        ----------
        value : str or None
            Native session or execution identity.

        Returns
        -------
        str or None
            Unchanged valid identity.

        Raises
        ------
        ValueError
            If an identity is blank, contains controls, or exceeds 64 UTF-8 bytes.
        """
        if value is not None and (not value.strip() or not value.isprintable()
                                  or len(value.encode("utf-8")) > 64):
            raise ValueError("ZCode identities must be printable, nonblank, and at most 64 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def validate_turn(self) -> "ZcodeHook":
        """Require the native execution identity for supported state changes.

        Returns
        -------
        ZcodeHook
            Validated callback.

        Raises
        ------
        ValueError
            If a supported callback omits its turn identity.
        """
        if self.task_state() is not None and self.turn_id is None:
            raise ValueError("A supported ZCode callback requires turnId")
        return self

    def task_state(self) -> TaskState | None:
        """Map lifecycle events without treating a tool failure as task failure.

        Returns
        -------
        TaskState or None
            Observed task state, or None for unsupported events.

        Notes
        -----
        Native hooks have no whole-turn interruption or model-failure callback.
        Even an interrupted tool can be recovered within the current turn.
        """
        return {
            "UserPromptSubmit": TaskState.RUNNING,
            "PreToolUse": TaskState.RUNNING,
            "PermissionRequest": TaskState.WAITING_INPUT,
            "PostToolUse": TaskState.RUNNING,
            "PostToolUseFailure": TaskState.RUNNING,
            "Stop": TaskState.COMPLETED,
        }.get(self.hook_event_name)

    def labels(self) -> tuple[str, str]:
        """Derive bounded task and workspace labels from public callback fields.

        Returns
        -------
        tuple[str, str]
            Prompt title and workspace basename.
        """
        return (display_text(self.prompt, 64) or "ZCode task",
                display_text(PureWindowsPath(self.cwd).name, 64))

    def detail(self) -> str:
        """Describe state without exposing tool arguments, results, or raw errors.

        Returns
        -------
        str
            Display detail bounded to 160 UTF-8 bytes.
        """
        if self.hook_event_name == "PermissionRequest":
            return display_text(f"Approval requested: {self.tool_name or 'tool'}", 160)
        if self.hook_event_name == "Stop":
            return display_text(self.last_assistant_message or "Turn ended", 160)
        if self.hook_event_name == "PostToolUseFailure":
            return "Tool failed; agent may recover"
        return "Working"
