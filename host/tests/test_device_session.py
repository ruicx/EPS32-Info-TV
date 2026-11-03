"""Exercise session ordering, recovery, and presentation feedback over a fake peer."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

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
            elif kind == "ping":
                response.pong.SetInParent()
            else:
                self.last_session = command.session_id
                if kind == "card_upsert" and self.withhold_cards:
                    continue
                response.acknowledgment.in_reply_to = command.message_id
                response.acknowledgment.stage = pb.ACK_STAGE_ACCEPTED
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
