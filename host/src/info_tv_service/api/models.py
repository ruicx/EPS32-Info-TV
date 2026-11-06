"""Strict local submission schemas and wire-compatible string validation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from info_tv_service.tasks.models import TaskEvent, TaskIcon, TaskState


class WeatherRequest(BaseModel):
    """Replace weather with producer-supplied values and bounded freshness."""

    model_config = ConfigDict(extra="forbid")
    location: str = Field(min_length=1, max_length=24, strict=True)
    temperature_c: int = Field(ge=-100, le=100, strict=True)
    condition: Literal["unknown", "clear", "cloudy", "rain", "snow", "storm", "fog"]
    valid_for_seconds: int = Field(default=1800, ge=1, le=3600, strict=True)
    daily_low_c: int | None = Field(default=None, ge=-100, le=100, strict=True)
    daily_high_c: int | None = Field(default=None, ge=-100, le=100, strict=True)

    @model_validator(mode="after")
    def validate_range(self) -> WeatherRequest:
        """Require both daily extremes in increasing order.

        Returns
        -------
        WeatherRequest
            Validated observation.

        Raises
        ------
        ValueError
            If the range is incomplete or reversed.
        """
        if (self.daily_low_c is None) != (self.daily_high_c is None):
            raise ValueError("Supply both daily_low_c and daily_high_c")
        if self.daily_low_c is not None and self.daily_high_c is not None and self.daily_low_c > self.daily_high_c:
            raise ValueError("daily_low_c must not exceed daily_high_c")
        return self

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str) -> str:
        """Validate the device's bounded city label.

        Parameters
        ----------
        value : str
            Submitted location.

        Returns
        -------
        str
            Unchanged nonblank location.

        Raises
        ------
        ValueError
            If the label is blank, contains controls, or exceeds 24 UTF-8 bytes.
        """
        if not value.strip() or not value.isprintable() or len(value.encode("utf-8")) > 24:
            raise ValueError("Location must be nonblank, printable, and at most 24 UTF-8 bytes")
        return value


class WeatherAlertRequest(BaseModel):
    """Replace one source-selected alert with ordered updates and remaining validity."""

    model_config = ConfigDict(extra="forbid")
    alert_id: UUID
    sequence: int = Field(gt=0, le=2**63 - 1, strict=True)
    title: str = Field(min_length=1, max_length=64, strict=True)
    source: str = Field(min_length=1, max_length=64, strict=True)
    location: str = Field(min_length=1, max_length=24, strict=True)
    severity: Literal["blue", "yellow", "orange", "red"]
    detail: str = Field(default="", max_length=160, strict=True)
    valid_for_seconds: int = Field(ge=1, le=86400, strict=True)

    @field_validator("title", "source", "location", "detail")
    @classmethod
    def validate_text(cls, value: str, info: ValidationInfo) -> str:
        """Check printable labels against their wire byte limits.

        Parameters
        ----------
        value : str
            Submitted text.
        info : ValidationInfo
            Field identity selecting the encoded limit.

        Returns
        -------
        str
            Unchanged valid label.

        Raises
        ------
        ValueError
            If a label is blank, contains controls, or exceeds its byte limit.
        """
        limit = 160 if info.field_name == "detail" else 24 if info.field_name == "location" else 64
        if (value and not value.isprintable()) or (info.field_name != "detail" and not value.strip()):
            raise ValueError("Alert labels must be printable and nonblank")
        if len(value.encode("utf-8")) > limit:
            raise ValueError(f"Text exceeds its {limit}-byte UTF-8 capacity")
        return value


class DeviceSettingsRequest(BaseModel):
    """Set an absolute backlight level without changing displayed messages."""

    model_config = ConfigDict(extra="forbid")
    brightness_percent: int = Field(ge=0, le=100, strict=True)


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
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    conversation_title: str = Field(default="", max_length=64)
    context: str = Field(default="", max_length=64)
    run_sequence: int | None = Field(default=None, gt=0, le=2**63 - 1, strict=True)
    icon: TaskIcon = TaskIcon.TASK

    @field_validator("source", "task_id", "title", "detail", "conversation_id", "conversation_title", "context")
    @classmethod
    def validate_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        """Reject embedded NUL characters.

        Parameters
        ----------
        value : str or None
            Submitted text.
        info : ValidationInfo
            Field identity for its encoded-byte limit.

        Returns
        -------
        str or None
            Unchanged valid text.

        Raises
        ------
        ValueError
            If text cannot be represented as a bounded C string.
        """
        if value is None:
            return None
        if "\0" in value:
            raise ValueError("NUL characters are not supported")
        limit = 160 if info.field_name == "detail" else 64
        if len(value.encode("utf-8")) > limit:
            raise ValueError(f"Text exceeds its {limit}-byte UTF-8 capacity")
        return value

    @model_validator(mode="after")
    def validate_conversation(self) -> TaskEventRequest:
        """Require an execution ordinal whenever a conversation is identified.

        Returns
        -------
        TaskEventRequest
            Validated request.

        Raises
        ------
        ValueError
            If conversation fields cannot identify and order an execution.
        """
        if (self.conversation_id is None) != (self.run_sequence is None):
            raise ValueError("conversation_id and run_sequence must be supplied together")
        if self.conversation_title and self.conversation_id is None:
            raise ValueError("conversation_title requires conversation_id")
        return self

    def to_event(self) -> TaskEvent:
        """Construct the immutable event after encoded-length validation.

        Returns
        -------
        TaskEvent
            Transport-independent event.

        """
        return TaskEvent(self.event_id.hex, self.source, self.task_id, self.sequence,
                         self.state, self.title, self.detail, self.progress_percent,
                         self.conversation_id, self.conversation_title, self.context, self.run_sequence,
                         self.icon)
