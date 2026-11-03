"""Demonstrate task progress and completion through the production HTTP API."""

import argparse
import json
import time
from urllib.request import Request, urlopen
from uuid import uuid4


def main() -> None:
    """Submit progress and completion using a unique task run identity.

    Raises
    ------
    urllib.error.URLError
        If the service is unavailable or rejects a submission.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    task_id = uuid4().hex
    for sequence, progress in enumerate(range(0, 101, 10), start=1):
        body = {"event_id": uuid4().hex, "source": "demo", "task_id": task_id,
                "sequence": sequence, "state": "completed" if progress == 100 else "running",
                "title": "Building firmware", "detail": "Build completed" if progress == 100 else "Compiling components",
                "progress_percent": progress}
        request = Request(args.url.rstrip("/") + "/v1/task-events", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            print(response.read().decode())
        if progress < 100:
            time.sleep(1)


if __name__ == "__main__":
    main()
