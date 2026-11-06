"""Exercise session ordering, recovery, and presentation feedback over a fake peer."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest

from info_tv_service.device.codec import make_envelope
from info_tv_service.device.framing import FrameDecoder, encode_frame
from info_tv_service.device.generated import device_pb2 as pb
from info_tv_service.device.session import DeviceSession
from info_tv_service.tasks.models import TaskEvent, TaskState
from info_tv_service.tasks.service import TaskService
from info_tv_service.tasks.store import AdmissionError, TaskStore


class PeerTransport:
    """Emulate protocol feedback without pretending every card was visible."""

    def __init__(self) -> None:
        """Initialize isolated peer buffers and captured operations."""
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self.decoder = FrameDecoder()
        self.commands: list[pb.Envelope] = []
        self.fail = False
        self.opens = 0
        self.withhold_cards = False
        self.last_session = ""
        self.task_icons = True
        self.brightness_control = True
        self.weather = True
        self.withhold_settings = False
        self.withhold_weather = False

    async def open(self) -> None:
        """Start a fresh connection while preserving captured history."""
        self.fail = False
        self.opens += 1
        self.incoming = asyncio.Queue()
        self.decoder.reset()

    async def close(self) -> None:
        """Release the peer's logical connection."""

    async def read(self) -> bytes:
        """Read a peer reply or signal an injected disconnect.

        Returns
        -------
        bytes
            Encoded feedback.

        Raises
        ------
        OSError
            For an injected disconnection.
        """
        if self.fail:
            raise OSError("Injected disconnect")
        return await self.incoming.get()

    async def write(self, data: bytes) -> None:
        """Decode host output and reply with the selected milestones.

        Parameters
        ----------
        data : bytes
            Host stream chunk.
        """
        for payload in self.decoder.feed(data):
            command = pb.Envelope.FromString(payload)
            self.commands.append(command)
            response = make_envelope(command.session_id)
            kind = command.WhichOneof("body")
            if kind == "hello":
                response.hello.boot_id = 123
                response.hello.max_cards = 8
                response.hello.task_icons = self.task_icons
                response.hello.brightness_control = self.brightness_control
                response.hello.weather = self.weather
            elif kind == "ping":
                response.pong.SetInParent()
            else:
                self.last_session = command.session_id
                if kind == "card_upsert" and self.withhold_cards:
                    continue
                if kind == "device_settings" and self.withhold_settings:
                    continue
                if kind == "weather" and self.withhold_weather:
                    continue
                response.acknowledgment.in_reply_to = command.message_id
                response.acknowledgment.stage = pb.ACK_STAGE_ACCEPTED
                if kind == "device_settings":
                    response.acknowledgment.stage = pb.ACK_STAGE_APPLIED
                    response.acknowledgment.brightness_percent = command.device_settings.brightness_percent
            self.incoming.put_nowait(encode_frame(response.SerializeToString()))


async def wait_until(condition: Callable[[], bool]) -> None:
    """Wait for a bounded asynchronous condition.

    Parameters
    ----------
    condition : Callable
        Completion predicate.

    Raises
    ------
    TimeoutError
        If the condition remains false after three seconds.
    """
    async with asyncio.timeout(3):
        while not condition():
            await asyncio.sleep(0.005)


async def stop(task: asyncio.Task[None]) -> None:
    """Cancel and await a test-owned coordinator.

    Parameters
    ----------
    task : Task
        Running device coordinator.
    """
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_coalescing_real_acceptance_and_no_fake_presentation() -> None:
    """Rapid changes coalesce and accepted content stays unpresented without feedback."""
    async def scenario() -> None:
        """Drive the production coordinator against a controlled peer."""
        peer = PeerTransport()
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        service = TaskService(store, session)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            for sequence in range(1, 21):
                service.submit_event(TaskEvent(uuid4().hex, "demo", "run", sequence, TaskState.RUNNING, "Build", progress_percent=sequence))
            await wait_until(lambda: any(message.HasField("card_upsert") for message in peer.commands))
            updates = [message for message in peer.commands if message.HasField("card_upsert")]
            assert len(updates) == 1
            assert updates[0].card_upsert.card.view.status.progress_percent == 20
            card = store.list_tasks()[0]
            await wait_until(lambda: session.card_status(card.card_id).get("accepted") is True)
            assert session.card_status(card.card_id)["presented"] is False
            response = make_envelope(session.session_id)
            response.acknowledgment.CopyFrom(pb.Acknowledgment(in_reply_to=updates[0].message_id, stage=pb.ACK_STAGE_PRESENTED, card_id=card.card_id, revision=card.revision))
            peer.incoming.put_nowait(encode_frame(response.SerializeToString()))
            await wait_until(lambda: session.card_status(card.card_id).get("presented") is True)
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_firmware_without_icons_is_rejected_before_snapshot() -> None:
    """An older peer cannot silently accept icon-bearing content."""
    async def scenario() -> None:
        """Advertise missing capability and inspect the connection diagnostic."""
        peer = PeerTransport()
        peer.task_icons = False
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: "task icons" in str(session.get_status()))
            assert not session.online
            assert not any(message.HasField("snapshot") for message in peer.commands)
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_reconnect_snapshots_current_state_without_replaying_completion() -> None:
    """Reconnect retains the service session and sends current state, not history."""
    async def scenario() -> None:
        """Disconnect after completion and inspect the next synchronization."""
        peer = PeerTransport()
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        service = TaskService(store, session)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            complete = TaskEvent(uuid4().hex, "demo", "run", 1, TaskState.COMPLETED, "Build", progress_percent=100)
            service.submit_event(complete)
            await wait_until(lambda: any(message.HasField("notification") for message in peer.commands))
            identity = session.session_id
            peer.fail = True
            await wait_until(lambda: not session.online)
            service.submit_event(replace(complete, event_id=uuid4().hex, sequence=2, detail="Final state"))
            await wait_until(lambda: peer.opens >= 2 and session.online)
            snapshots = [message for message in peer.commands if message.HasField("snapshot")]
            assert snapshots[-1].snapshot.cards[0].view.status.detail == "Final state"
            assert session.session_id == identity
            assert sum(message.HasField("notification") for message in peer.commands) == 1
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_notification_overload_does_not_commit_the_rejected_update() -> None:
    """Capacity is checked before accepting a state transition that needs a notice."""
    async def scenario() -> None:
        """Fill the outbox in one event-loop turn, before the sender can drain it."""
        peer = PeerTransport()
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        service = TaskService(store, session)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            for sequence in range(1, 17):
                service.submit_event(TaskEvent(uuid4().hex, "demo", "run", sequence, TaskState.WAITING_INPUT if sequence % 2 else TaskState.RUNNING, "Build"))
            before = store.list_tasks()
            try:
                service.submit_event(TaskEvent(uuid4().hex, "demo", "run", 17, TaskState.FAILED, "Build"))
            except AdmissionError as error:
                assert error.status_code == 503
            else:
                raise AssertionError("Full notification queue was admitted")
            assert store.list_tasks() == before
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_lost_accepted_feedback_retries_the_same_operation_identity() -> None:
    """An unacknowledged transmission retains its operation identity."""
    async def scenario() -> None:
        """Withhold first acceptance, then allow the retry to complete."""
        peer = PeerTransport()
        peer.withhold_cards = True
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        service = TaskService(store, session)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            service.submit_event(TaskEvent(uuid4().hex, "demo", "run", 1, TaskState.RUNNING, "Build"))
            await wait_until(lambda: any(message.HasField("card_upsert") for message in peer.commands))
            peer.withhold_cards = False
            card = store.list_tasks()[0]
            await wait_until(lambda: session.card_status(card.card_id).get("accepted") is True)
            updates = [message for message in peer.commands if message.HasField("card_upsert")]
            assert len(updates) == 2
            assert updates[0].message_id == updates[1].message_id
            assert updates[0].card_upsert.card.revision == updates[1].card_upsert.card.revision
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_notifications_are_not_starved_by_pending_cards() -> None:
    """Task-update delivery yields to notices before draining every dirty card."""
    async def scenario() -> None:
        """Queue two independent cards and one completion in a single turn."""
        peer = PeerTransport()
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        service = TaskService(store, session)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            service.submit_event(TaskEvent(uuid4().hex, "demo", "done", 1, TaskState.COMPLETED, "Build"))
            service.submit_event(TaskEvent(uuid4().hex, "demo", "other", 1, TaskState.RUNNING, "Other"))
            await wait_until(lambda: sum(message.HasField("card_upsert") for message in peer.commands) == 2)
            kinds = [message.WhichOneof("body") for message in peer.commands if message.WhichOneof("body") in ("card_upsert", "notification")]
            assert kinds == ["card_upsert", "notification", "card_upsert"]
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_brightness_coalesces_requires_applied_and_resynchronizes_zero() -> None:
    """Distinguish request/admission/application and restore zero after reconnect."""
    async def scenario() -> None:
        """Inject wrong-stage/value feedback before completing the real setting."""
        peer = PeerTransport()
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            assert session.settings_status()["applied_brightness_percent"] == 100
            peer.withhold_settings = True
            for percent in (10, 30, 70):
                session.set_brightness(percent)
            await wait_until(lambda: any(message.HasField("device_settings") and
                message.device_settings.brightness_percent == 70 for message in peer.commands))
            commands = [message for message in peer.commands if message.HasField("device_settings")]
            assert [message.device_settings.brightness_percent for message in commands] == [100, 70]
            command = commands[-1]
            response = make_envelope(session.session_id)
            ack = response.acknowledgment
            ack.in_reply_to = command.message_id
            ack.stage = pb.ACK_STAGE_ACCEPTED
            session._handle_feedback(response)
            assert session.settings_status()["applied_brightness_percent"] == 100
            ack.stage = pb.ACK_STAGE_APPLIED
            session._handle_feedback(response)  # A missing reported value is not known zero.
            ack.brightness_percent = 71
            session._handle_feedback(response)
            assert session.settings_status()["applied_brightness_percent"] == 100
            ack.brightness_percent = 70
            ack.in_reply_to = "unrelated"
            session._handle_feedback(response)
            assert session.settings_status()["applied_brightness_percent"] == 100
            ack.in_reply_to = command.message_id
            peer.incoming.put_nowait(encode_frame(response.SerializeToString()))
            await wait_until(lambda: session.settings_status()["applied_brightness_percent"] == 70)
            assert session.settings_status()["delivery"] == {
                "message_id": command.message_id, "applied": True, "error": None}
            assert not session._deliveries[command.message_id].presented
            session._deliveries.clear()  # Simulate eviction from bounded operation history.
            assert session.settings_status()["delivery"] == {
                "message_id": command.message_id, "applied": True, "error": None}
            peer.withhold_settings = False
            session.set_brightness(0)
            await wait_until(lambda: session.settings_status()["applied_brightness_percent"] == 0)
            peer.fail = True
            await wait_until(lambda: not session.online)
            assert session.settings_status()["applied_brightness_percent"] is None
            await wait_until(lambda: peer.opens >= 2 and session.online)
            assert session.settings_status()["brightness_percent"] == 0
            assert session.settings_status()["applied_brightness_percent"] == 0
            assert store.list_tasks() == []
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_brightness_retry_retains_identity_and_reports_hardware_failure() -> None:
    """Retry one absolute operation without claiming success after rejection."""
    async def scenario() -> None:
        """Lose a settings reply, then reject the retried operation."""
        peer = PeerTransport()
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            peer.withhold_settings = True
            session.set_brightness(30)
            await wait_until(lambda: sum(message.HasField("device_settings") and
                message.device_settings.brightness_percent == 30 for message in peer.commands) >= 2)
            commands = [message for message in peer.commands if message.HasField("device_settings")
                        and message.device_settings.brightness_percent == 30]
            assert commands[0].message_id == commands[1].message_id
            response = make_envelope(session.session_id)
            response.error.in_reply_to = commands[0].message_id
            response.error.code = pb.ERROR_CODE_HARDWARE
            response.error.detail = "PWM failed"
            peer.incoming.put_nowait(encode_frame(response.SerializeToString()))
            await wait_until(lambda: "PWM failed" in str(session.settings_status()))
            assert session.settings_status()["applied_brightness_percent"] == 100
            assert not session._deliveries[commands[0].message_id].applied
            peer.withhold_settings = False
            session.set_brightness(30)
            await wait_until(lambda: session.settings_status()["applied_brightness_percent"] == 30)
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_firmware_without_brightness_is_rejected_before_snapshot() -> None:
    """An unsupported device cannot silently ignore target brightness."""
    async def scenario() -> None:
        """Advertise missing brightness capability and inspect the diagnostic."""
        peer = PeerTransport()
        peer.brightness_control = False
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: "brightness control" in str(session.get_status()))
            assert not session.online
            assert not any(message.HasField("snapshot") for message in peer.commands)
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_weather_coalesces_expires_and_does_not_revive_on_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the original weather deadline through retries and reconnects.

    Parameters
    ----------
    monkeypatch : MonkeyPatch
        Shortens only command retry timing for this scenario.
    """
    async def scenario() -> None:
        """Exercise real delivery scheduling against a controlled peer."""
        monkeypatch.setattr("info_tv_service.device.session.ACK_TIMEOUT_SECONDS", 0.1)
        peer = PeerTransport()
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        session.set_weather(pb.Weather(location="Harbin", temperature_c=0,
                                       condition=pb.WEATHER_CONDITION_SNOW, valid_for_ms=1000))
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: session.online)
            snapshot = next(command for command in peer.commands if command.HasField("snapshot"))
            assert snapshot.snapshot.weather.HasField("temperature_c")
            assert snapshot.snapshot.weather.temperature_c == 0
            assert cast(dict[str, object], session.weather_status()["delivery"])["accepted"] is True
            peer.withhold_weather = True
            for temperature in (10, 20, 30):
                session.set_weather(pb.Weather(location="Shanghai", temperature_c=temperature,
                                               condition=pb.WEATHER_CONDITION_CLEAR, valid_for_ms=250))
            await wait_until(lambda: len([c for c in peer.commands if c.HasField("weather")]) >= 2)
            updates = [c for c in peer.commands if c.HasField("weather")]
            assert updates[0].message_id == updates[1].message_id
            assert updates[0].weather.temperature_c == updates[1].weather.temperature_c == 30
            assert 0 < updates[1].weather.valid_for_ms < updates[0].weather.valid_for_ms <= 250
            peer.withhold_weather = False
            response = make_envelope(session.session_id)
            response.acknowledgment.in_reply_to = updates[0].message_id
            response.acknowledgment.stage = pb.ACK_STAGE_ACCEPTED
            peer.incoming.put_nowait(encode_frame(response.SerializeToString()))
            await wait_until(lambda: cast(dict[str, object], session.weather_status()["delivery"]).get("accepted") is True)
            await wait_until(lambda: session.weather_status()["state"] == "stale")
            assert session.weather_status()["temperature_c"] == 30
            assert not session._deliveries[updates[0].message_id].presented
            peer.fail = True
            await wait_until(lambda: peer.opens >= 2 and session.online)
            snapshots = [c for c in peer.commands if c.HasField("snapshot")]
            assert not snapshots[-1].snapshot.weather.HasField("temperature_c")
            session.set_weather(pb.Weather())
            await wait_until(lambda: cast(dict[str, object], session.weather_status()["delivery"]).get("accepted") is True)
            assert session.weather_status()["state"] == "unavailable"
            assert store.list_tasks() == []
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_firmware_without_weather_is_rejected_before_snapshot() -> None:
    """An older device cannot silently drop the persistent weather area."""
    async def scenario() -> None:
        """Advertise unsupported weather and inspect handshake failure."""
        peer = PeerTransport()
        peer.weather = False
        store = TaskStore()
        session = DeviceSession(peer, store.list_tasks)
        task = asyncio.create_task(session.run())
        try:
            await wait_until(lambda: "weather status" in str(session.get_status()))
            assert not any(command.HasField("snapshot") for command in peer.commands)
        finally:
            await stop(task)
    asyncio.run(scenario())
