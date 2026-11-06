"""Cross-language HTTP-to-firmware-core integration, without serial hardware."""

import asyncio
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from info_tv_service.app import create_app
from info_tv_service.config import Settings


class FirmwareBridgeTransport:
    """Run the native C++ codec/presentation peer as an ordered byte stream."""

    def __init__(self, executable: Path) -> None:
        """Configure an isolated peer process.

        Parameters
        ----------
        executable : Path
            Native protocol_bridge executable built by firmware/tests.
        """
        self._executable = executable
        self._process: asyncio.subprocess.Process | None = None

    async def open(self) -> None:
        """Start the C++ peer with binary stdin/stdout pipes."""
        self._process = await asyncio.create_subprocess_exec(str(self._executable), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)

    async def read(self) -> bytes:
        """Read framed C++ feedback.

        Returns
        -------
        bytes
            Raw peer stream chunk.

        Raises
        ------
        OSError
            If the peer terminates or was not started.
        """
        if self._process is None or self._process.stdout is None:
            raise OSError("Bridge not started")
        data = await self._process.stdout.read(4096)
        if not data:
            raise OSError("Bridge exited")
        return data

    async def write(self, data: bytes) -> None:
        """Write the production host's binary frames to the peer.

        Parameters
        ----------
        data : bytes
            Encoded host stream chunk.

        Raises
        ------
        OSError
            If the peer has no writable stream.
        """
        if self._process is None or self._process.stdin is None:
            raise OSError("Bridge not started")
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    async def close(self) -> None:
        """Close input and await or terminate the owned test process."""
        if self._process is not None:
            if self._process.stdin is not None:
                self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), 2)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
            self._process = None


@pytest.mark.integration
def test_http_to_cpp_firmware_core() -> None:
    """Verify actual Python/C++ codec compatibility and separate UI milestones."""
    root = Path(__file__).resolve().parents[2]
    suffix = ".exe" if os.name == "nt" else ""
    default = root / "build/native-tests" / ("Debug" if os.name == "nt" else "") / f"protocol_bridge{suffix}"
    executable = Path(os.environ.get("INFO_TV_PROTOCOL_BRIDGE", str(default)))
    if not executable.exists():
        pytest.skip("Build firmware/tests to enable the native cross-language integration")
    with TestClient(create_app(Settings("native-bridge"), FirmwareBridgeTransport(executable))) as client:
        deadline = time.monotonic() + 5
        while client.get("/v1/device").json()["state"] != "online":
            assert time.monotonic() < deadline, "C++ handshake did not finish"
            time.sleep(0.01)
        assert client.put("/v1/weather", json={
            "location": "Harbin", "temperature_c": 0, "condition": "snow",
            "daily_low_c": -10, "daily_high_c": 0,
        }).status_code == 202
        while not client.get("/v1/weather").json()["delivery"].get("accepted"):
            assert time.monotonic() < deadline, "C++ weather was not admitted"
            time.sleep(0.01)
        assert client.get("/v1/tasks").json() == []
        assert client.put("/v1/device/settings", json={"brightness_percent": 0}).status_code == 202
        while client.get("/v1/device/settings").json()["applied_brightness_percent"] != 0:
            assert time.monotonic() < deadline, "C++ brightness setting was not applied"
            time.sleep(0.01)
        body = {"event_id": uuid4().hex, "source": "demo", "task_id": "cpp-build", "sequence": 1,
                "state": "running", "title": "Python to C++", "progress_percent": 42, "icon": "test"}
        assert client.post("/v1/task-events", json=body).status_code == 202
        while not client.get("/v1/tasks").json()[0]["delivery"].get("accepted"):
            assert time.monotonic() < deadline, "Backlight-off card was not admitted"
            time.sleep(0.01)
        assert not client.get("/v1/tasks").json()[0]["delivery"]["presented"]
        assert client.put("/v1/device/settings", json={"brightness_percent": 30}).status_code == 202
        while client.get("/v1/device/settings").json()["applied_brightness_percent"] != 30:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        while True:
            tasks = client.get("/v1/tasks").json()
            if tasks[0]["delivery"].get("presented"):
                assert tasks[0]["delivery"]["accepted"]
                break
            assert time.monotonic() < deadline, "C++ UI did not report visibility"
            time.sleep(0.01)
        body.update(event_id=uuid4().hex, sequence=2, state="completed", progress_percent=100)
        assert client.post("/v1/task-events", json=body).json()["notification"] == "queued"
        while True:
            deliveries = client.get("/v1/device").json()["deliveries"]
            # Card presentations carry a :card_id key; notification feedback does not.
            if any(item["accepted"] and item["presented"] and ":" not in item["message_id"] for item in deliveries):
                break
            assert time.monotonic() < deadline, "C++ notification was not presented"
            time.sleep(0.01)


        alert = {"alert_id": uuid4().hex, "sequence": 1, "title": "Snow",
                 "location": "Harbin", "source": "Demo bureau", "severity": "orange",
                 "detail": "Synthetic integration test.", "valid_for_seconds": 3600}
        assert client.put("/v1/weather/alert", json=alert).status_code == 202
        while not client.get("/v1/weather/alert").json()["delivery"].get("notification_presented"):
            assert time.monotonic() < deadline, "C++ alert notification was not presented"
            time.sleep(0.01)
        assert client.get("/v1/weather/alert").json()["delivery"]["accepted"]
        assert len(client.get("/v1/tasks").json()) == 1
        assert client.delete("/v1/weather/alert").status_code == 202
        while not client.get("/v1/weather/alert").json()["delivery"].get("accepted"):
            assert time.monotonic() < deadline, "C++ alert withdrawal was not admitted"
            time.sleep(0.01)
        assert client.get("/v1/weather").json()["daily_low_c"] == -10
        card_id = client.get("/v1/tasks").json()[0]["card_id"]
        prior = {item["message_id"] for item in client.get("/v1/device").json()["deliveries"]}
        assert client.delete(f"/v1/tasks/{card_id}").json()["removed"]
        deadline = time.monotonic() + 5
        while not any(item["accepted"] and item["message_id"] not in prior
                      for item in client.get("/v1/device").json()["deliveries"]):
            assert time.monotonic() < deadline, "C++ removal snapshot was not admitted"
            time.sleep(0.01)
        assert client.get("/v1/tasks").json() == []
        assert client.get("/v1/device").json()["state"] == "online"


@pytest.mark.integration
def test_eight_conversations_reach_the_cpp_overview_pages() -> None:
    """Every row, including later pages, receives actual core visibility feedback."""
    root = Path(__file__).resolve().parents[2]
    executable = root / "build/native-tests" / ("Debug" if os.name == "nt" else "") / (
        "protocol_bridge.exe" if os.name == "nt" else "protocol_bridge")
    executable = Path(os.environ.get("INFO_TV_PROTOCOL_BRIDGE", str(executable)))
    if not executable.exists():
        pytest.skip("Build firmware/tests to enable the native cross-language integration")
    with TestClient(create_app(Settings("native-bridge"), FirmwareBridgeTransport(executable))) as client:
        deadline = time.monotonic() + 5
        while client.get("/v1/device").json()["state"] != "online":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        for index in range(8):
            submission = {"event_id": uuid4().hex, "source": "codex" if index % 2 else "agy",
                          "task_id": f"run-{index}", "conversation_id": f"thread-{index}",
                          "conversation_title": "消息接口", "context": "info_tv", "run_sequence": 1,
                          "sequence": 1, "state": "running", "title": "Review", "detail": "Checking protocol"}
            assert client.post("/v1/task-events", json=submission).status_code == 202
        records = client.get("/v1/tasks").json()
        assert len(records) == 8
        assert len({record["card_id"] for record in records}) == 8
        deadline = time.monotonic() + 20
        while not all(record["delivery"].get("presented") for record in client.get("/v1/tasks").json()):
            assert time.monotonic() < deadline, "Later overview pages never became visible"
            time.sleep(0.02)
