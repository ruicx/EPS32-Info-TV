"""Validate YAML configuration and preserve the existing serial-only CLI."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from info_tv_service.__main__ import main
from info_tv_service.config import Settings, load_settings


def test_yaml_example_loads_shanghai_and_cli_overrides_ports() -> None:
    """The committed example enables weather and supports explicit CLI overrides."""
    path = Path(__file__).resolve().parents[1] / "config.example.yaml"
    settings = load_settings(path)
    assert settings.weather is not None
    assert settings.weather.location == "Shanghai"
    assert settings.completed_retention_seconds == 300
    assert (settings.usb_vid, settings.usb_pid) == (0x303A, 0x1001)
    with (
        patch.object(sys, "argv", ["info-tv", "--config", str(path), "--serial-port", "COM9", "--http-port", "9876"]),
        patch("info_tv_service.cli.create_app") as create,
        patch("info_tv_service.cli.uvicorn.run"),
    ):
        main()
    passed = create.call_args.args[0]
    assert passed.serial_port == "COM9"
    assert passed.http_port == 9876
    assert passed.weather == settings.weather


@pytest.mark.parametrize("content", [
    "", "[]", "serial_port: COM6\nunknown: true", "serial_port: COM6\nhttp_port: true",
    "serial_port: COM6\ncompleted_retention_seconds: 0", "serial_port: [",
    "serial_port: COM6\nweather: {location: Shanghai, latitude: 91, longitude: 121}",
    "serial_port: COM6\nweather: {location: ' ', latitude: 31, longitude: 121}",
])
def test_invalid_configuration_is_rejected(content: str) -> None:
    """Reject malformed settings before any network or serial resources open.

    Parameters
    ----------
    content : str
        Invalid YAML document or configuration.
    """
    with patch.object(Path, "read_text", return_value=content), pytest.raises(ValueError):
        load_settings(Path("invalid.yaml"))


def test_serial_only_cli_keeps_automatic_weather_disabled() -> None:
    """Existing invocations do not acquire unexpected network behavior."""
    with (
        patch.object(sys, "argv", ["info-tv", "--serial-port", "COM6"]),
        patch("info_tv_service.cli.create_app") as create,
        patch("info_tv_service.cli.uvicorn.run"),
    ):
        main()
    assert create.call_args.args[0] == Settings("COM6")


def test_omitted_serial_port_defaults_to_auto_in_yaml_and_cli() -> None:
    """Allow startup without knowing the operating-system port number."""
    with patch.object(Path, "read_text", return_value="http_port: 9876"):
        assert load_settings(Path("auto.yaml")) == Settings(http_port=9876)
    with patch("info_tv_service.cli.create_app") as create, patch("info_tv_service.cli.uvicorn.run"):
        main(["serve"])
    assert create.call_args.args[0] == Settings(serial_port="auto")


@pytest.mark.parametrize("content", ["usb_vid: 0x1234\nusb_pid: 0x5678", "usb_vid: 4660\nusb_pid: 22136"])
def test_yaml_usb_ids_accept_hexadecimal_and_decimal_integers(content: str) -> None:
    """Carry explicit USB IDs into settings and preserve them with port overrides.

    Parameters
    ----------
    content : str
        Equivalent USB IDs in either supported integer notation.
    """
    with (
        patch.object(Path, "read_text", return_value=content),
        patch("info_tv_service.cli.create_app") as create,
        patch("info_tv_service.cli.uvicorn.run"),
    ):
        main(["serve", "--config", "custom.yaml", "--serial-port", "COM9"])
    assert create.call_args.args[0] == Settings("COM9", usb_vid=0x1234, usb_pid=0x5678)


@pytest.mark.parametrize("content", [
    "usb_vid: -1", "usb_vid: 65536", "usb_vid: true", "usb_vid: '0x303A'",
    "usb_pid: -1", "usb_pid: 65536", "usb_pid: false", "usb_pid: 1.5",
])
def test_yaml_usb_ids_reject_noninteger_or_out_of_range_values(content: str) -> None:
    """Reject malformed USB filters before discovery starts.

    Parameters
    ----------
    content : str
        Invalid unsigned 16-bit USB identifier.
    """
    with patch.object(Path, "read_text", return_value=content), pytest.raises(ValueError):
        load_settings(Path("invalid.yaml"))
