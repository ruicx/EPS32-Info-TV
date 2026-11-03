"""Strict local submission schemas and wire-compatible string validation."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from info_tv_service.tasks.models import TaskEvent, TaskState


class TaskEventRequest(BaseModel):
    """Accept a task run update without device addresses or layout fields."""

    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    source: str = Field(min_length=1, max_length=64)
    task_id: str = Field(min_length=1, max_length=64)
    sequence: int = Field(gt=0, le=2**63 - 1, strict=True)
    state: TaskState
    title: str = Field(min_length=1, max_length=64)
    detail: str = Field(default="", max_length=160)
    progress_percent: int | None = Field(default=None, ge=0, le=100, strict=True)

    @field_validator("source", "task_id", "title", "detail")
    @classmethod
    def validate_text(cls, value: str, info: ValidationInfo) -> str:
        """Reject embedded NUL characters.

        Parameters
        ----------
        value : str
            Submitted text.
        info : ValidationInfo
            Field identity for its encoded-byte limit.

        Returns
        -------
        str
            Unchanged valid text.

        Raises
        ------
        ValueError
            If text cannot be represented as a bounded C string.
        """
        if "\0" in value:
            raise ValueError("NUL characters are not supported")
        limit = 160 if info.field_name == "detail" else 64
        if len(value.encode("utf-8")) > limit:
            raise ValueError(f"Text exceeds its {limit}-byte UTF-8 capacity")
        return value

    def to_event(self) -> TaskEvent:
        """Construct the immutable event after encoded-length validation.

        Returns
        -------
        TaskEvent
            Transport-independent event.

        """
        return TaskEvent(self.event_id.hex, self.source, self.task_id, self.sequence,
                         self.state, self.title, self.detail, self.progress_percent)
