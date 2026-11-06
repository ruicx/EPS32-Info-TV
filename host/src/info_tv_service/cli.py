"""Start the host or call its HTTP API from a terminal or script."""

import argparse
import json
import logging
import math
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import uvicorn

from info_tv_service.app import create_app
from info_tv_service.config import Settings, load_settings
from info_tv_service.device.serial_ports import list_serial_ports
from info_tv_service.tasks.models import TaskIcon, TaskState


def build_parser() -> argparse.ArgumentParser:
    """Build the server and producer command tree.

    Returns
    -------
    argparse.ArgumentParser
        Parser whose client commands carry an HTTP method, path, and body fields.
    """
    parser = argparse.ArgumentParser(description="Start or control the info_tv host service")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Host API base URL (client commands)")
    parser.add_argument("--timeout", type=float, default=5, help="HTTP timeout in seconds (default: 5)")
    commands = parser.add_subparsers(dest="command", required=True)

    server = commands.add_parser("serve", help="Start the host service")
    server.add_argument("--config", type=Path, help="UTF-8 YAML configuration file")
    server.add_argument("--serial-port", help="auto (default), COM6, /dev/ttyACM0, or /dev/cu.usbmodem...")
    server.add_argument("--http-port", type=int)

    ports = commands.add_parser("ports", help="List local serial ports and automatic-selection candidates")
    ports.add_argument("--config", type=Path, help="YAML configuration supplying USB VID/PID filters")

    status = commands.add_parser("status", help="Query device connection and delivery health")
    status.set_defaults(method="GET", endpoint="/v1/device", fields=())

    task = commands.add_parser("task", help="Submit, list, or close tasks")
    tasks = task.add_subparsers(dest="action", required=True)
    listing = tasks.add_parser("list", help="List current cards and delivery feedback")
    listing.set_defaults(method="GET", endpoint="/v1/tasks", fields=())
    close = tasks.add_parser("close", help="Close a card using its ID from task list")
    close.add_argument("card_id", type=UUID)
    close.set_defaults(method="DELETE", endpoint="/v1/tasks/{card_id}", fields=())
    submit = tasks.add_parser("submit", help="Submit one ordered task event")
    submit.add_argument("--source", default="cli")
    submit.add_argument("--task-id", required=True, help="Stable ID for this execution")
    submit.add_argument("--sequence", required=True, type=int, help="Increasing update number within the execution")
    submit.add_argument("--state", required=True, choices=list(TaskState))
    submit.add_argument("--title", required=True)
    submit.add_argument("--event-id", type=UUID, help="Retain the same UUID and all fields when retrying")
    submit.add_argument("--detail", default="")
    submit.add_argument("--progress-percent", type=int)
    submit.add_argument("--icon", choices=list(TaskIcon), default="task")
    submit.add_argument("--conversation-id")
    submit.add_argument("--run-sequence", type=int)
    submit.add_argument("--conversation-title", default="")
    submit.add_argument("--context", default="")
    submit.set_defaults(method="POST", endpoint="/v1/task-events", fields=(
        "source", "task_id", "sequence", "state", "title", "event_id", "detail",
        "progress_percent", "icon", "conversation_id", "run_sequence", "conversation_title", "context",
    ))

    weather = commands.add_parser("weather", help="Query or replace retained weather")
    weather_commands = weather.add_subparsers(dest="action", required=True)
    get_weather = weather_commands.add_parser("get", help="Query weather freshness and delivery")
    get_weather.set_defaults(method="GET", endpoint="/v1/weather", fields=())
    clear_weather = weather_commands.add_parser("clear", help="Clear weather until the next producer update")
    clear_weather.set_defaults(method="DELETE", endpoint="/v1/weather", fields=())
    updater = weather_commands.add_parser("updater", help="Query automatic weather retrieval health")
    updater.set_defaults(method="GET", endpoint="/v1/weather/updater", fields=())
    set_weather = weather_commands.add_parser("set", help="Publish current weather")
    set_weather.add_argument("--location", required=True)
    set_weather.add_argument("--temperature-c", type=int, required=True)
    set_weather.add_argument("--condition", required=True, choices=["unknown", "clear", "cloudy", "rain", "snow", "storm", "fog"])
    set_weather.add_argument("--valid-for-seconds", type=int, default=1800)
    set_weather.add_argument("--daily-low-c", type=int)
    set_weather.add_argument("--daily-high-c", type=int)
    set_weather.set_defaults(method="PUT", endpoint="/v1/weather", fields=(
        "location", "temperature_c", "condition", "valid_for_seconds", "daily_low_c", "daily_high_c",
    ))

    alert = commands.add_parser("alert", help="Query, publish, or withdraw a weather alert")
    alerts = alert.add_subparsers(dest="action", required=True)
    get_alert = alerts.add_parser("get", help="Query current alert and notification delivery")
    get_alert.set_defaults(method="GET", endpoint="/v1/weather/alert", fields=())
    clear_alert = alerts.add_parser("clear", help="Withdraw the current alert")
    clear_alert.set_defaults(method="DELETE", endpoint="/v1/weather/alert", fields=())
    set_alert = alerts.add_parser("set", help="Publish one ordered alert update")
    set_alert.add_argument("--alert-id", required=True, type=UUID)
    set_alert.add_argument("--sequence", required=True, type=int)
    set_alert.add_argument("--title", required=True)
    set_alert.add_argument("--source", required=True)
    set_alert.add_argument("--location", required=True)
    set_alert.add_argument("--severity", required=True, choices=["blue", "yellow", "orange", "red"])
    set_alert.add_argument("--detail", default="")
    set_alert.add_argument("--valid-for-seconds", required=True, type=int)
    set_alert.set_defaults(method="PUT", endpoint="/v1/weather/alert", fields=(
        "alert_id", "sequence", "title", "source", "location", "severity", "detail", "valid_for_seconds",
    ))

    brightness = commands.add_parser("brightness", help="Query brightness or set it to 0..100")
    brightness.add_argument("brightness_percent", type=int, nargs="?")
    brightness.set_defaults(endpoint="/v1/device/settings", fields=("brightness_percent",))
    return parser


def serve(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Start a single-worker service bound exclusively to IPv4 loopback.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed server options, overriding YAML settings.
    parser : argparse.ArgumentParser
        Parser used to report configuration errors with exit code 2.
    """
    if args.http_port is not None and not 1 <= args.http_port <= 65535:
        parser.error("--http-port must be between 1 and 65535")
    try:
        settings = load_settings(args.config) if args.config else Settings(args.serial_port or "auto")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.serial_port is not None:
        settings = replace(settings, serial_port=args.serial_port)
    if args.http_port is not None:
        settings = replace(settings, http_port=args.http_port)
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.http_port, workers=1)


def main(argv: Sequence[str] | None = None) -> None:
    """Start the service or print a single API response as JSON.

    Parameters
    ----------
    argv : Sequence[str] or None
        Arguments without the executable; None reads the process command line.

    Raises
    ------
    SystemExit
        Code 1 for HTTP, connection, or response errors; code 2 for usage errors.

    Notes
    -----
    Legacy invocations beginning with a server option still start the service.
    Client requests bypass environment proxies and are never retried implicitly.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0].split("=", 1)[0] in {"--config", "--serial-port", "--http-port"}:
        arguments.insert(0, "serve")
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.command == "serve":
        serve(args, parser)
        return
    if args.command == "ports":
        try:
            settings = load_settings(args.config) if args.config else Settings()
        except (OSError, ValueError) as error:
            parser.error(str(error))
        try:
            print(json.dumps(list_serial_ports(settings.usb_vid, settings.usb_pid), ensure_ascii=False, indent=2))
        except OSError as error:
            print(f"Serial enumeration failed: {error}", file=sys.stderr)
            raise SystemExit(1) from error
        return
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite positive number")
    if args.command == "task" and args.action == "submit":
        args.event_id = (args.event_id or uuid4()).hex
    if args.command == "alert" and args.action == "set":
        args.alert_id = args.alert_id.hex
    if args.command == "brightness":
        if args.brightness_percent is not None and not 0 <= args.brightness_percent <= 100:
            parser.error("brightness must be between 0 and 100")
        args.method = "GET" if args.brightness_percent is None else "PUT"
    payload = {field: getattr(args, field) for field in args.fields if getattr(args, field) is not None}
    endpoint = args.endpoint.format(card_id=args.card_id.hex) if hasattr(args, "card_id") else args.endpoint
    try:
        with httpx.Client(timeout=args.timeout, trust_env=False) as client:
            response = client.request(args.method, args.url.rstrip("/") + endpoint, json=payload or None)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as error:
        print(f"HTTP {error.response.status_code}: {error.response.text}", file=sys.stderr)
        raise SystemExit(1) from error
    except (httpx.RequestError, httpx.InvalidURL, ValueError) as error:
        print(f"Request failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))
