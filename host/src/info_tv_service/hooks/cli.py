"""Run a short-lived agent hook sender or flush its saved outbox."""

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

import httpx

from info_tv_service.hooks.agy import AgyHook
from info_tv_service.hooks.agy_store import AgyStore
from info_tv_service.hooks.codex import CodexHook
from info_tv_service.hooks.outbox import HookOutbox
from info_tv_service.hooks.store import CodexStore


def default_state_path(source: str = "codex") -> Path:
    """Locate persistent per-user state independently of agent workspaces.

    Parameters
    ----------
    source : str
        Selected producer namespace.

    Returns
    -------
    Path
        Windows local application data path, with a portable home fallback.
    """
    root = Path(os.environ["LOCALAPPDATA"]) if "LOCALAPPDATA" in os.environ else Path.home() / ".local/state"
    return root / f"info_tv/{source}-hooks.sqlite3"


def flush_pending(store: HookOutbox, client: httpx.Client, url: str) -> None:
    """Send queued events in order within a short callback delivery window.

    Parameters
    ----------
    store : HookOutbox
        Persistent queue shared by independent hook processes.
    client : httpx.Client
        Local HTTP client with a short request timeout.
    url : str
        Service base URL.

    Raises
    ------
    httpx.HTTPError
        If a submission cannot be delivered or is rejected.
    ValueError
        If the response is not a task admission acknowledgment.

    Notes
    -----
    Concurrent senders can send the same UUID; the host deduplicates it.
    Nothing is deleted until a valid acknowledgment is received.
    """
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        pending = store.next_pending()
        if pending is None:
            return
        event_id, payload = pending
        response = client.post(url.rstrip("/") + "/v1/task-events", content=payload.encode("utf-8"),
                               headers={"Content-Type": "application/json"})
        response.raise_for_status()
        result = response.json()
        if response.status_code != 202 or not isinstance(result, dict) or result.get("outcome") not in (
            "accepted", "duplicate", "stale", "closed",
        ):
            raise ValueError("Host did not acknowledge the task event; retained for retry")
        store.acknowledge(event_id)


def main(argv: Sequence[str] | None = None) -> None:
    """Read native UTF-8 JSON, save a transition, and attempt delivery.

    Parameters
    ----------
    argv : Sequence[str] or None
        Arguments without the executable, or None for the process command line.

    Notes
    -----
    Runtime failures print diagnostics to stderr and neutral JSON to stdout.
    They never return a blocking hook exit code or policy decision. Failed HTTP
    requests remain pending for the next callback or an explicit flush.
    """
    parser = argparse.ArgumentParser(description="Forward agent hooks to the local info_tv service")
    parser.add_argument("source", choices=["codex", "agy"])
    parser.add_argument("event", nargs="?", choices=["PreInvocation", "Stop"],
                        help="Required native event name for agy callbacks")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--timeout", type=float, default=0.5, help="HTTP timeout in seconds")
    parser.add_argument("--flush", action="store_true", help="Retry pending events without reading stdin")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("--timeout must be a finite positive number")
        path = args.state_file or default_state_path(args.source)
        if args.source == "codex":
            if args.event is not None:
                raise ValueError("Codex reads its event name from stdin")
            codex_hook = None if args.flush else CodexHook.model_validate_json(sys.stdin.buffer.read())
            with closing(CodexStore(path)) as codex_store:
                if codex_hook is not None:
                    codex_store.capture(codex_hook)
        else:
            if not args.flush and args.event is None:
                raise ValueError("agy requires PreInvocation or Stop as its event argument")
            agy_hook = None
            if not args.flush:
                payload = json.loads(sys.stdin.buffer.read())
                if not isinstance(payload, dict):
                    raise ValueError("agy callback must be a JSON object")
                agy_hook = AgyHook.model_validate(payload | {"event": args.event})
            with closing(AgyStore(path)) as agy_store:
                if agy_hook is not None:
                    agy_store.capture(agy_hook)
        with closing(HookOutbox(path)) as store, httpx.Client(timeout=args.timeout, trust_env=False) as client:
            flush_pending(store, client, args.url)
    except (OSError, sqlite3.Error, ValueError, httpx.HTTPError, httpx.InvalidURL) as error:
        print(f"info-tv-hook: {error}", file=sys.stderr)
    print("{}")
