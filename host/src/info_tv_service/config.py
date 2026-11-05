"""Immutable runtime configuration."""

from dataclasses import dataclass

MAX_TASKS = 8
EVENT_CACHE_CAPACITY = 256
NOTIFICATION_QUEUE_CAPACITY = 8
NOTIFICATION_VALIDITY_MS = 30_000
ACK_TIMEOUT_SECONDS = 1.0
MAX_SEND_ATTEMPTS = 3
HEARTBEAT_INTERVAL_SECONDS = 1.0
HEARTBEAT_TIMEOUT_SECONDS = 3.0
RECONNECT_SECONDS = 1.0


@dataclass(frozen=True)
class Settings:
    """Configure one local service and one serial device.

    Parameters
    ----------
    serial_port : str
        Operating-system serial path.
    http_port : int
        Loopback HTTP port.
    """

    serial_port: str
    http_port: int = 8765
