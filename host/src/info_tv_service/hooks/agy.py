"""Interpret Antigravity CLI invocation and stop hooks without policy decisions."""

from pathlib import PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from info_tv_service.hooks.text import display_text
from info_tv_service.tasks.models import TaskState


class AgyHook(BaseModel):
    """Read supported camelCase fields and the explicitly configured event name."""

    model_config = ConfigDict(extra="ignore", strict=True)
    event: Literal["PreInvocation", "Stop"]
    conversation_id: str = Field(alias="conversationId")
    last_user_input: str = Field(alias="lastUserInput")
    workspace_paths: list[str] = Field(default_factory=list, alias="workspacePaths")
    invocation_num: int | None = Field(default=None, ge=0, le=2**63 - 1, alias="invocationNum")
    initial_num_steps: int | None = Field(default=None, ge=1, le=2**63 - 1, alias="initialNumSteps")
    fully_idle: bool | None = Field(default=None, alias="fullyIdle")
    termination_reason: str | None = Field(default=None, alias="terminationReason")

    @field_validator("conversation_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        """Keep the native conversation identity within the host contract.

        Parameters
        ----------
        value : str
            Source-provided opaque identity.

        Returns
        -------
        str
            Unchanged valid identity.

        Raises
        ------
        ValueError
            If the identity is blank, contains controls, or exceeds 64 bytes.
        """
        if not value.strip() or not value.isprintable() or len(value.encode("utf-8")) > 64:
            raise ValueError("agy conversationId must be printable, nonblank, and at most 64 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> "AgyHook":
        """Require the fields needed to interpret the selected callback.

        Returns
        -------
        AgyHook
            Validated native callback.

        Raises
        ------
        ValueError
            If invocation counters or explicit stop fields are absent.
        """
        if self.event == "PreInvocation" and (self.invocation_num is None or self.initial_num_steps is None):
            raise ValueError("PreInvocation requires invocationNum and initialNumSteps")
        if self.event == "Stop" and (self.fully_idle is None or self.termination_reason is None):
            raise ValueError("Stop requires fullyIdle and terminationReason")
        return self

    def task_state(self) -> TaskState | None:
        """Map explicit execution outcomes, ignoring later model cycles.

        Returns
        -------
        TaskState or None
            Running for the first invocation, or a recognized idle stop state.
            Unknown reasons and stops with background work are ignored.
        """
        if self.event == "PreInvocation":
            return TaskState.RUNNING if self.invocation_num == 0 else None
        if not self.fully_idle:
            return None
        return {
            "NO_TOOL_CALL": TaskState.COMPLETED,
            "ERROR": TaskState.FAILED,
            "MAX_INVOCATIONS": TaskState.FAILED,
            "MAX_FORCED_INVOCATIONS": TaskState.FAILED,
            "MAX_TOKEN_BUDGET_EXCEEDED": TaskState.FAILED,
            "USER_CANCELED": TaskState.INTERRUPTED,
        }.get(self.termination_reason or "")

    def labels(self) -> tuple[str, str]:
        """Derive bounded labels without reading transcript or artifact paths.

        Returns
        -------
        tuple[str, str]
            Prompt title and the first workspace's basename.
        """
        workspace = self.workspace_paths[0] if self.workspace_paths else ""
        return (display_text(self.last_user_input, 64) or "AGY task",
                display_text(PureWindowsPath(workspace).name, 64))

    def detail(self) -> str:
        """Describe an explicit outcome without forwarding native error text.

        Returns
        -------
        str
            Fixed display text for the mapped state or reason.
        """
        return {
            "NO_TOOL_CALL": "Turn ended",
            "ERROR": "Execution error",
            "MAX_INVOCATIONS": "Invocation limit reached",
            "MAX_FORCED_INVOCATIONS": "Continuation limit reached",
            "MAX_TOKEN_BUDGET_EXCEEDED": "Token budget exceeded",
            "USER_CANCELED": "Turn interrupted",
        }.get(self.termination_reason or "", "Working")
