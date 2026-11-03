"""Command-line entry point for the local display service."""

import argparse
import logging

import uvicorn

from info_tv_service.app import create_app
from info_tv_service.config import Settings


def main() -> None:
    """Start a single-worker server bound exclusively to IPv4 loopback."""
    parser = argparse.ArgumentParser(description="info_tv local display service")
    parser.add_argument("--serial-port", required=True, help="COM6, /dev/ttyACM0, or /dev/cu.usbmodem...")
    parser.add_argument("--http-port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.http_port <= 65535:
        parser.error("--http-port must be between 1 and 65535")
    logging.basicConfig(level=logging.INFO)
    settings = Settings(args.serial_port, args.http_port)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.http_port, workers=1)


if __name__ == "__main__":
    main()
