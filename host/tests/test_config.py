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
    with (
        patch.object(sys, "argv", ["info-tv", "--config", str(path), "--serial-port", "COM9", "--http-port", "9876"]),
        patch("info_tv_service.__main__.create_app") as create,
        patch("info_tv_service.__main__.uvicorn.run"),
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
        patch("info_tv_service.__main__.create_app") as create,
        patch("info_tv_service.__main__.uvicorn.run"),
    ):
        main()
    assert create.call_args.args[0] == Settings("COM6")
