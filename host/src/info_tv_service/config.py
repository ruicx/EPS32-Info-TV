"""Immutable runtime configuration."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TASKS = 8
EVENT_CACHE_CAPACITY = 256
NOTIFICATION_QUEUE_CAPACITY = 8
NOTIFICATION_VALIDITY_MS = 30_000
ACK_TIMEOUT_SECONDS = 1.0
MAX_SEND_ATTEMPTS = 3
HEARTBEAT_INTERVAL_SECONDS = 1.0
HEARTBEAT_TIMEOUT_SECONDS = 3.0
RECONNECT_SECONDS = 1.0
DEFAULT_USB_VID = 0x303A
DEFAULT_USB_PID = 0x1001


class WeatherSettings(BaseModel):
    """Configure automatic Open-Meteo retrieval for one explicit location."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    location: str = Field(min_length=1, max_length=24, strict=True)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False, strict=True)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True)
    refresh_seconds: int = Field(default=900, ge=60, strict=True)
    retry_seconds: int = Field(default=60, ge=1, strict=True)
    valid_for_seconds: int = Field(default=1800, ge=1, le=3600, strict=True)

    @model_validator(mode="after")
    def validate_location(self) -> "WeatherSettings":
        """Require a printable label that fits the device.

        Returns
        -------
        WeatherSettings
            Validated immutable settings.

        Raises
        ------
        ValueError
            If the label is blank, contains controls, or exceeds 24 UTF-8 bytes.
        """
        if not self.location.strip() or not self.location.isprintable() or len(self.location.encode("utf-8")) > 24:
            raise ValueError("Weather location must be printable, nonblank, and at most 24 UTF-8 bytes")
        return self


@dataclass(frozen=True)
class Settings:
    """Configure one local service and one serial device.

    Parameters
    ----------
    serial_port : str
        Operating-system serial path, or auto for USB discovery.
    http_port : int
        Loopback HTTP port.
    completed_retention_seconds : int
        Time to retain a completed execution from its first completed update.
    weather : WeatherSettings or None
        Automatic retrieval configuration; absent disables network requests.
    usb_vid : int
        USB vendor ID used for automatic serial discovery.
    usb_pid : int
        USB product ID used for automatic serial discovery.
    """

    serial_port: str = "auto"
    http_port: int = 8765
    completed_retention_seconds: int = 300
    weather: WeatherSettings | None = None
    usb_vid: int = DEFAULT_USB_VID
    usb_pid: int = DEFAULT_USB_PID


class FileSettings(BaseModel):
    """Validate YAML keys and values before constructing runtime settings."""

    model_config = ConfigDict(extra="forbid")
    serial_port: str = Field(default="auto", min_length=1, strict=True)
    http_port: int = Field(default=8765, ge=1, le=65535, strict=True)
    completed_retention_seconds: int = Field(default=300, ge=1, strict=True)
    weather: WeatherSettings | None = None
    usb_vid: int = Field(default=DEFAULT_USB_VID, ge=0, le=0xFFFF, strict=True)
    usb_pid: int = Field(default=DEFAULT_USB_PID, ge=0, le=0xFFFF, strict=True)


def load_settings(path: Path) -> Settings:
    """Read and validate an explicitly selected YAML configuration.

    Parameters
    ----------
    path : Path
        UTF-8 YAML file containing service settings.

    Returns
    -------
    Settings
        Validated runtime settings.

    Raises
    ------
    OSError
        If the file cannot be read.
    ValueError
        If YAML or its configuration values are invalid.
    """
    try:
        values = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML: {error}") from error
    validated = FileSettings.model_validate(values)
    return Settings(validated.serial_port, validated.http_port,
                    validated.completed_retention_seconds, validated.weather,
                    validated.usb_vid, validated.usb_pid)
