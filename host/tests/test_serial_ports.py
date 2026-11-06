"""Verify metadata-based serial discovery and reconnect port changes."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from serial.tools.list_ports_common import ListPortInfo

from info_tv_service.cli import main
from info_tv_service.config import Settings, load_settings
from info_tv_service.device.serial_ports import resolve_serial_port
from info_tv_service.device.serial_transport import SerialTransport
from info_tv_service.runtime import ServiceRuntime


def make_port(device: str, vid: int | None = 0x303A, pid: int | None = 0x1001) -> ListPortInfo:
    """Construct enumerated metadata without accessing hardware.

    Parameters
    ----------
    device : str
        Operating-system port path.
    vid : int or None
        Reported USB vendor ID.
    pid : int or None
        Reported USB product ID.

    Returns
    -------
    ListPortInfo
        Synthetic port with a readable label and stable serial number.
    """
    port = ListPortInfo(device, skip_link_detection=True)
    port.vid = vid
    port.pid = pid
    port.description = "Test USB device"
    port.serial_number = "test-device"
    return port


def test_auto_selects_single_usb_candidate_and_ignores_other_ports() -> None:
    """Require the recorded USB pair rather than any available serial device."""
    ports = [make_port("COM1", None, None), make_port("COM4", 0x303A, 0x9999), make_port("COM6")]
    with patch("info_tv_service.device.serial_ports.list_ports.comports", return_value=ports):
        assert resolve_serial_port("auto") == "COM6"


@pytest.mark.parametrize("candidates,reason", [([], "No USB serial candidate"), (["COM6", "COM9"], "Multiple USB serial candidates")])
def test_auto_refuses_missing_or_ambiguous_candidates(candidates: list[str], reason: str) -> None:
    """Keep discovery deterministic without selecting an arbitrary port.

    Parameters
    ----------
    candidates : list[str]
        Zero or multiple matching paths.
    reason : str
        Expected diagnostic.
    """
    ports = [make_port(device) for device in candidates]
    with (
        patch("info_tv_service.device.serial_ports.list_ports.comports", return_value=ports),
        pytest.raises(OSError, match=reason),
    ):
        resolve_serial_port("auto")


def test_explicit_port_bypasses_enumeration() -> None:
    """Preserve manual selection for unusual adapters and multiple devices."""
    with patch("info_tv_service.device.serial_ports.list_ports.comports") as enumerate_ports:
        assert resolve_serial_port("COM9") == "COM9"
        assert resolve_serial_port("/dev/ttyACM0") == "/dev/ttyACM0"
    enumerate_ports.assert_not_called()


def test_transport_rescans_after_port_number_changes() -> None:
    """Resolve the port again on each worker opening after a disconnect."""
    async def reconnect() -> None:
        """Exercise two real transport-worker lifecycles with mock serial I/O."""
        with (
            patch("info_tv_service.device.serial_ports.list_ports.comports",
                  side_effect=[[make_port("COM6", 0x1234, 0x5678)],
                               [make_port("COM9", 0x1234, 0x5678)]]) as enumerate_ports,
            patch("info_tv_service.device.serial_transport.serial.Serial") as factory,
        ):
            connection = factory.return_value
            connection.in_waiting = 0
            connection.read.side_effect = OSError("Test disconnect")
            transport = SerialTransport("auto", usb_vid=0x1234, usb_pid=0x5678)
            for expected in ["COM6", "COM9"]:
                try:
                    await transport.open()
                    assert connection.port == expected
                finally:
                    await transport.close()
            assert enumerate_ports.call_count == 2
            assert connection.open.call_count == 2

    asyncio.run(reconnect())


def test_transport_reports_missing_device_without_opening_any_port() -> None:
    """Propagate discovery failure through the existing offline retry boundary."""
    async def connect() -> None:
        """Wait for worker failure and ensure cleanup completes."""
        with (
            patch("info_tv_service.device.serial_ports.list_ports.comports", return_value=[]),
            patch("info_tv_service.device.serial_transport.serial.Serial") as factory,
        ):
            transport = SerialTransport("auto")
            try:
                with pytest.raises(OSError, match="No USB serial candidate"):
                    await transport.open()
            finally:
                await transport.close()
            factory.return_value.open.assert_not_called()

    asyncio.run(connect())


def test_ports_cli_lists_metadata_without_api_or_serial_access(capsys: pytest.CaptureFixture[str]) -> None:
    """Make discovery inspectable even when the host service is not running.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    with (
        patch("info_tv_service.device.serial_ports.list_ports.comports",
              return_value=[make_port("COM6"), make_port("COM1", None, None)]),
        patch("info_tv_service.cli.httpx.Client") as client,
        patch("info_tv_service.device.serial_transport.serial.Serial") as serial,
    ):
        main(["ports"])
    ports = json.loads(capsys.readouterr().out)
    assert ports[0]["port"] == "COM1" and ports[0]["candidate"] is False
    assert ports[0]["vid"] is None and ports[0]["pid"] is None
    assert ports[1] == {"port": "COM6", "description": "Test USB device", "vid": "303A",
                        "pid": "1001", "serial_number": "test-device", "candidate": True}
    client.assert_not_called()
    serial.assert_not_called()


def test_ports_cli_reports_enumeration_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """Report unavailable system metadata as a CLI failure.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    with (
        patch("info_tv_service.device.serial_ports.list_ports.comports", side_effect=OSError("Unavailable")),
        pytest.raises(SystemExit) as error,
    ):
        main(["ports"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert not output.out and "Serial enumeration failed" in output.err


def test_yaml_filters_reach_runtime_and_ports_cli(capsys: pytest.CaptureFixture[str]) -> None:
    """Use the same YAML filter for service discovery and candidate inspection.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    with patch.object(Path, "read_text", return_value="usb_vid: 0x1234\nusb_pid: 0x5678"):
        settings = load_settings(Path("custom.yaml"))
        with patch("info_tv_service.runtime.SerialTransport") as factory:
            ServiceRuntime(settings)
        factory.assert_called_once_with("auto", 0x1234, 0x5678)
        with patch("info_tv_service.device.serial_ports.list_ports.comports",
                   return_value=[make_port("COM6"), make_port("COM9", 0x1234, 0x5678)]):
            main(["ports", "--config", "custom.yaml"])
    ports = json.loads(capsys.readouterr().out)
    assert ports[0]["candidate"] is False
    assert ports[1]["candidate"] is True


def test_custom_usb_filter_is_reflected_in_missing_device_error() -> None:
    """Show the actual requested identity when no device matches."""
    settings = Settings(usb_vid=0x1234, usb_pid=0x5678)
    with (
        patch("info_tv_service.device.serial_ports.list_ports.comports", return_value=[make_port("COM6")]),
        pytest.raises(OSError, match="1234:5678"),
    ):
        resolve_serial_port("auto", settings.usb_vid, settings.usb_pid)
