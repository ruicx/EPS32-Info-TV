"""Submit five simulated Codex/agy conversations through the real local API.

Notes
-----
This demonstrates display behavior; it does not integrate or launch agent clients.
Two important notices play before the two-page conversation overview.
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
        ("codex", "Message API", "info_tv", "waiting_input", "Confirm notification retention"),
        ("agy", "Login flow", "webapp", "failed", "Build failed; inspect the computer"),
        ("codex", "Unit tests", "info_tv", "running", "Checking protocol compatibility"),
        ("agy", "Documentation", "webapp", "running", "Updating API examples"),
        ("codex", "UI review", "info_tv", "running", "Checking screen layouts"),
    ]
    for source, title, context, state, detail in examples:
        body = {"event_id": uuid4().hex, "source": source, "task_id": uuid4().hex,
                "conversation_id": uuid4().hex, "conversation_title": title,
                "context": context, "run_sequence": 1, "sequence": 1,
                "state": state, "title": title, "detail": detail}
        request = Request(args.url.rstrip("/") + "/v1/task-events",
                          data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            print(response.read().decode())


if __name__ == "__main__":
    main()
