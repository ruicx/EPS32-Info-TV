"""Command-line entry point for the local display service."""

import argparse
import logging
from dataclasses import replace
from pathlib import Path

import uvicorn

from info_tv_service.app import create_app
from info_tv_service.config import Settings, load_settings


def main() -> None:
    """Start a single-worker server bound exclusively to IPv4 loopback."""
    parser = argparse.ArgumentParser(description="info_tv local display service")
    parser.add_argument("--config", type=Path, help="UTF-8 YAML configuration file")
    parser.add_argument("--serial-port", help="COM6, /dev/ttyACM0, or /dev/cu.usbmodem...")
    parser.add_argument("--http-port", type=int)
    args = parser.parse_args()
    if args.http_port is not None and not 1 <= args.http_port <= 65535:
        parser.error("--http-port must be between 1 and 65535")
    if args.config is None and not args.serial_port:
        parser.error("Supply --config or --serial-port")
    try:
        settings = load_settings(args.config) if args.config else Settings(args.serial_port)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.serial_port is not None:
        settings = replace(settings, serial_port=args.serial_port)
    if args.http_port is not None:
        settings = replace(settings, http_port=args.http_port)
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.http_port, workers=1)


if __name__ == "__main__":
    main()
