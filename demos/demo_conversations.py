"""Submit five simulated Codex/agy conversations through the real local API.

Notes
-----
This demonstrates display behavior; it does not integrate or launch agent clients.
Two important notices play before the five-row conversation overview.
"""

import argparse
import json
from urllib.request import Request, urlopen
from uuid import uuid4


def main() -> None:
    """Create independent conversation cards with recognizable display labels.

    Raises
    ------
    urllib.error.URLError
        If the local service is unavailable or rejects a submission.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    examples = [
        ("codex", "Message API", "info_tv", "waiting_input", "Confirm notification retention", "code", None),
        ("agy", "Login flow", "webapp", "failed", "Build failed; inspect the computer", "build", 35),
        ("codex", "Unit tests", "info_tv", "running", "Checking protocol compatibility", "test", 42),
        ("agy", "Documentation", "webapp", "running", "Updating API examples", "task", None),
        ("codex", "UI review", "info_tv", "running", "Checking screen layouts", "review", 0),
    ]
    for source, title, context, state, detail, icon, progress in examples:
        body = {"event_id": uuid4().hex, "source": source, "task_id": uuid4().hex,
                "conversation_id": uuid4().hex, "conversation_title": title,
                "context": context, "run_sequence": 1, "sequence": 1,
                "state": state, "title": title, "detail": detail,
                "icon": icon, "progress_percent": progress}
        request = Request(args.url.rstrip("/") + "/v1/task-events",
                          data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            print(response.read().decode())


if __name__ == "__main__":
    main()
