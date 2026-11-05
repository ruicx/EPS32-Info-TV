# Physical Display Demos

Manual display scenarios use the production host HTTP API and firmware. They
do not open the serial port directly or require a demo-specific firmware build.
These scripts are not pytest/CTest cases and are not run by automated test discovery.

## Setup

1. Connect the ESP32 with the info_tv firmware already flashed.
2. Start the host service if it is not already running:

   ```powershell
   uv run --project host info-tv --serial-port COM6
   ```

   Replace COM6 with the current device port. Use one host instance per device.

3. Check `http://127.0.0.1:8765/v1/device` for `"state": "online"` before starting
   a demo. Offline HTTP acceptance alone does not produce a visible notification.

Run all commands from the repository root.

## Task Progress and Completion

```powershell
uv run --project host python demos/demo_task.py
```

The screen shows `Building firmware` progressing from 0% to 100% in ten seconds.
Completion generates an ordinary `NOTIFICATION`, followed approximately five
seconds later by the task overview. Each submission prints the host's admission
response; device Accepted/Presented feedback is available through `/v1/tasks`
and `/v1/device`.

To use a different local service port:

```powershell
uv run --project host python demos/demo_task.py --url http://127.0.0.1:8766
```

Each run creates a new task identity. Existing tasks remain visible and rotate
in the three-row, six-second paged overview. The current demo retains up to eight
conversation/task cards until host restart;
restart the host to clear them before another set of demonstrations.

Keep additional manual display scenarios here. Protocol generation and other
development operations remain under `scripts/`.

## Multiple conversations

Use the updated host and firmware, and start with an empty host store (the demo
adds five of its eight available cards):

```powershell
uv run --project host python demos/demo_conversations.py
```

This submits five simulated Codex/agy conversations, not real agent-client hooks.
Two important notices show first, followed by the three-row overview across two
pages. Waiting/failed conversations sort first. Ordinary progress does not restart
the six-second page timer. Repeat runs create new conversation identities, so
restart the host to clear the current demo before repeating it.
