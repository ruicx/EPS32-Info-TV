"""Enumerate USB serial metadata without opening or resetting devices."""

from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

from info_tv_service.config import DEFAULT_USB_PID, DEFAULT_USB_VID


def is_candidate(port: ListPortInfo, usb_vid: int = DEFAULT_USB_VID, usb_pid: int = DEFAULT_USB_PID) -> bool:
    """Match the configured USB identity.

    Parameters
    ----------
    port : ListPortInfo
        Operating-system serial metadata.
    usb_vid : int
        Target USB vendor ID.
    usb_pid : int
        Target USB product ID.

    Returns
    -------
    bool
        Whether VID/PID matches; this does not identify the firmware.
    """
    return (port.vid, port.pid) == (usb_vid, usb_pid)


def list_serial_ports(usb_vid: int = DEFAULT_USB_VID, usb_pid: int = DEFAULT_USB_PID) -> list[dict[str, object]]:
    """List ports and their selection metadata without probing the protocol.

    Parameters
    ----------
    usb_vid : int
        Target USB vendor ID used for the candidate flag.
    usb_pid : int
        Target USB product ID used for the candidate flag.

    Returns
    -------
    list[dict[str, object]]
        Port paths, descriptions, USB IDs, serial numbers, and candidate flags.
    """
    return [
        {"port": port.device, "description": port.description,
         "vid": f"{port.vid:04X}" if port.vid is not None else None,
         "pid": f"{port.pid:04X}" if port.pid is not None else None,
         "serial_number": port.serial_number, "candidate": is_candidate(port, usb_vid, usb_pid)}
        for port in sorted(list_ports.comports())
    ]


def resolve_serial_port(port: str, usb_vid: int = DEFAULT_USB_VID, usb_pid: int = DEFAULT_USB_PID) -> str:
    """Resolve automatic selection anew for each connection attempt.

    Parameters
    ----------
    port : str
        Explicit device path, or ``auto`` to select one USB candidate.
    usb_vid : int
        Target USB vendor ID.
    usb_pid : int
        Target USB product ID.

    Returns
    -------
    str
        Explicit path unchanged, or the single matching enumerated port.

    Raises
    ------
    OSError
        If automatic discovery finds zero or multiple matching candidates.

    Notes
    -----
    Other ESP32 boards can share this USB ID. Existing protocol negotiation
    still validates compatibility after opening the selected port.
    """
    if port != "auto":
        return port
    candidates = sorted(item.device for item in list_ports.comports() if is_candidate(item, usb_vid, usb_pid))
    if not candidates:
        raise OSError(f"No USB serial candidate ({usb_vid:04X}:{usb_pid:04X}); connect the device or use --serial-port. See info-tv ports.")
    if len(candidates) > 1:
        raise OSError(f"Multiple USB serial candidates: {', '.join(candidates)}; select one with --serial-port.")
    return candidates[0]
