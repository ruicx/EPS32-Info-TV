"""One device session with bounded delivery, synchronization, and feedback."""

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
import logging
import time
from uuid import uuid4

from info_tv_service.config import (
    ACK_TIMEOUT_SECONDS, EVENT_CACHE_CAPACITY, HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_TIMEOUT_SECONDS, MAX_SEND_ATTEMPTS, NOTIFICATION_QUEUE_CAPACITY,
    NOTIFICATION_VALIDITY_MS, RECONNECT_SECONDS,
)
from info_tv_service.device.codec import decode_feedback, make_envelope
from info_tv_service.device.framing import FrameDecoder, encode_frame
from info_tv_service.device.generated import device_pb2 as pb
from info_tv_service.device.transport import ByteTransport
from info_tv_service.device.views import build_card
from info_tv_service.tasks.models import TaskRecord


@dataclass
class Delivery:
    """Track reception and visibility separately for one operation.

    Parameters
    ----------
    message_id : str
        Original operation identity.
    accepted : bool
        Whether UI-side acceptance was reported.
    presented : bool
        Whether visible first-refresh completion was reported.
    error : str or None
        Rejection or uncertain delivery outcome.
    """

    message_id: str
    accepted: bool = False
    presented: bool = False
    error: str | None = None


@dataclass
class Pending:
    """Retain one command until Accepted or bounded delivery failure.

    Parameters
    ----------
    envelope : Envelope
        Operation retaining its identity across retries.
    sent_at : float
        Most recent monotonic send time in seconds.
    attempts : int
        Number of transmissions, including the original send.
    expires_at : float or None
        Original monotonic notification deadline, if applicable.
    """

    envelope: pb.Envelope
    sent_at: float
    attempts: int = 1
    expires_at: float | None = None


class DeviceSession:
    """Own one connection and coalesce task cards independently of notifications."""

    def __init__(self, transport: ByteTransport, tasks: Callable[[], list[TaskRecord]]) -> None:
        """Create a new service-process session.

        Parameters
        ----------
        transport : ByteTransport
            Concrete device byte stream.
        tasks : Callable
            Read current immutable task records for recovery snapshots.
        """
        self.session_id = uuid4().hex
        self._transport = transport
        self._tasks = tasks
        self._decoder = FrameDecoder()
        self._received: deque[pb.Envelope] = deque()
        self._dirty: dict[str, pb.Card] = {}
        self._notifications: deque[tuple[pb.Notification, float]] = deque()
        self._deliveries: OrderedDict[str, Delivery] = OrderedDict()
        self._card_delivery: dict[str, tuple[int, str]] = {}
        self._pending: Pending | None = None
        self._state = "offline"
        self._last_error: str | None = None
        self._last_received = 0.0
        self._last_ping = 0.0
        self._card_sent_since_notice = False
        self._logger = logging.getLogger(__name__)

    @property
    def online(self) -> bool:
        """Return whether overview synchronization completed.

        Returns
        -------
        bool
            True only after the current snapshot was accepted by the UI.
        """
        return self._state == "online"

    def can_notify(self) -> bool:
        """Check bounded pending notification admission.

        Returns
        -------
        bool
            Whether an online transition can be queued atomically.
        """
        self._expire_notifications()
        return len(self._notifications) < NOTIFICATION_QUEUE_CAPACITY

    def publish_card(self, card: pb.Card) -> None:
        """Replace an unsent revision for the same card.

        Parameters
        ----------
        card : Card
            Current generic card content.
        """
        self._dirty[card.card_id] = card

    def enqueue_notification(self, notification: pb.Notification) -> None:
        """Admit an online notification after a same-turn capacity check.

        Parameters
        ----------
        notification : Notification
            One event whose original validity must not be renewed.
        """
        self._notifications.append((notification, time.monotonic() + NOTIFICATION_VALIDITY_MS / 1000))

    def get_status(self) -> dict[str, object]:
        """Expose connection state without claiming visibility from transmission.

        Returns
        -------
        dict[str, object]
            JSON-compatible diagnostics and bounded recent delivery records.
        """
        return {
            "state": self._state, "session_id": self.session_id,
            "last_error": self._last_error,
            "deliveries": [
                {"message_id": key, "accepted": value.accepted, "presented": value.presented, "error": value.error}
                for key, value in self._deliveries.items()
            ],
        }

    def card_status(self, card_id: str) -> dict[str, object]:
        """Read the latest sent revision's delivery milestones.

        Parameters
        ----------
        card_id : str
            Device card identity.

        Returns
        -------
        dict[str, object]
            Latest correlated delivery, if one was sent.
        """
        current = self._card_delivery.get(card_id)
        if current is None:
            return {"state": "pending"}
        revision, message_id = current
        delivery = self._deliveries.get(f"{message_id}:{card_id}")
        return {"revision": revision, "message_id": message_id,
                "accepted": bool(delivery and delivery.accepted),
                "presented": bool(delivery and delivery.presented),
                "error": delivery.error if delivery else None}

    def _expire_notifications(self) -> None:
        """Remove unsent notifications past their original host deadline."""
        now = time.monotonic()
        self._notifications = deque((note, deadline) for note, deadline in self._notifications if deadline > now)

    async def run(self) -> None:
        """Maintain the connection until cancelled by the application lifespan.

        Notes
        -----
        Expected transport failures reconnect. Unexpected programming errors
        propagate to the runtime supervisor instead of being hidden.
        """
        while True:
            try:
                await self._transport.open()
                self._decoder.reset()
                self._received.clear()
                await self._connected_loop()
            except (OSError, TimeoutError) as error:
                reason = str(error)
                if reason != self._last_error:
                    self._logger.warning("Device offline: %s", reason)
                self._last_error = reason
            finally:
                self._state = "offline"
                self._notifications.clear()
                if self._pending is not None:
                    self._mark_error(self._pending.envelope.message_id, "Connection lost; outcome may be unknown")
                self._pending = None
                await self._transport.close()
            await asyncio.sleep(RECONNECT_SECONDS)

    async def _send(self, envelope: pb.Envelope) -> None:
        """Serialize and transmit an envelope.

        Parameters
        ----------
        envelope : Envelope
            Complete typed operation.
        """
        await self._transport.write(encode_frame(envelope.SerializeToString()))

    async def _receive(self, timeout: float) -> pb.Envelope | None:
        """Read a validated feedback message with a bounded wait.

        Parameters
        ----------
        timeout : float
            Maximum wait in seconds.

        Returns
        -------
        Envelope or None
            One valid envelope or no message before the deadline.
        """
        if self._received:
            return self._received.popleft()
        try:
            chunk = await asyncio.wait_for(self._transport.read(), timeout)
        except TimeoutError:
            return None
        for payload in self._decoder.feed(chunk):
            envelope = decode_feedback(payload)
            if envelope is not None:
                self._received.append(envelope)
        return self._received.popleft() if self._received else None

    async def _connected_loop(self) -> None:
        """Handshake, synchronize, and service one ordered device connection.

        Raises
        ------
        TimeoutError
            If handshake, acknowledgment, or heartbeat fails.
        OSError
            If transport or synchronization fails.
        """
        self._state = "handshaking"
        hello = make_envelope("")
        hello.hello.SetInParent()
        await self._send(hello)
        deadline = time.monotonic() + HEARTBEAT_TIMEOUT_SECONDS
        while True:
            response = await self._receive(0.1)
            if response is not None and response.WhichOneof("body") == "hello" and response.hello.boot_id:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Device Hello timeout")
        self._state = "synchronizing"
        self._last_received = time.monotonic()
        snapshot = make_envelope(self.session_id)
        snapshot.snapshot.cards.extend(build_card(record) for record in self._tasks())
        self._dirty.clear()
        await self._start_command(snapshot)
        while True:
            now = time.monotonic()
            if now - self._last_received >= HEARTBEAT_TIMEOUT_SECONDS:
                raise TimeoutError("Device heartbeat timeout")
            if now - self._last_ping >= HEARTBEAT_INTERVAL_SECONDS:
                ping = make_envelope(self.session_id)
                ping.ping.SetInParent()
                await self._send(ping)
                self._last_ping = now
            response = await self._receive(0.02)
            if response is not None and response.session_id == self.session_id:
                if response.WhichOneof("body") == "hello":
                    raise OSError("Device restarted")
                self._last_received = time.monotonic()
                self._handle_feedback(response)
            if self._pending is not None:
                await self._retry_if_due()
            elif self.online:
                self._expire_notifications()
                if self._notifications and (not self._dirty or self._card_sent_since_notice):
                    selected = 0
                    for index, (candidate, _) in enumerate(self._notifications):
                        if candidate.priority == pb.PRIORITY_IMPORTANT:
                            selected = index
                            break
                    note, expires = self._notifications[selected]
                    del self._notifications[selected]
                    command = make_envelope(self.session_id)
                    command.notification.CopyFrom(note)
                    command.notification.valid_for_ms = max(1, int((expires - time.monotonic()) * 1000))
                    self._card_sent_since_notice = False
                    await self._start_command(command, expires)
                elif self._dirty:
                    card_id = next(iter(self._dirty))
                    command = make_envelope(self.session_id)
                    command.card_upsert.card.CopyFrom(self._dirty.pop(card_id))
                    self._card_sent_since_notice = True
                    await self._start_command(command)

    async def _start_command(self, envelope: pb.Envelope, expires: float | None = None) -> None:
        """Record command correlation before asynchronous transmission.

        Parameters
        ----------
        envelope : Envelope
            Snapshot, card update, or notification.
        expires : float or None
            Original monotonic notification validity deadline.
        """
        self._pending = Pending(envelope, time.monotonic(), expires_at=expires)
        cards = list(envelope.snapshot.cards) if envelope.HasField("snapshot") else []
        if envelope.HasField("card_upsert"):
            cards.append(envelope.card_upsert.card)
        self._deliveries[envelope.message_id] = Delivery(envelope.message_id)
        for card in cards:
            self._card_delivery[card.card_id] = (card.revision, envelope.message_id)
            self._deliveries[f"{envelope.message_id}:{card.card_id}"] = Delivery(envelope.message_id)
        while len(self._deliveries) > EVENT_CACHE_CAPACITY:
            self._deliveries.popitem(last=False)
        await self._send(envelope)

    def _mark_error(self, message_id: str, reason: str) -> None:
        """Record a correlated terminal delivery failure.

        Parameters
        ----------
        message_id : str
            Original host operation identity.
        reason : str
            Device rejection or host uncertainty.
        """
        for key, delivery in self._deliveries.items():
            if key == message_id or key.startswith(message_id + ":"):
                delivery.error = reason

    def _handle_feedback(self, envelope: pb.Envelope) -> None:
        """Apply correlated device feedback without acknowledging feedback.

        Parameters
        ----------
        envelope : Envelope
            Structurally validated current-session response.

        Raises
        ------
        OSError
            If the required recovery snapshot was rejected.
        """
        if envelope.HasField("error"):
            identity = envelope.error.in_reply_to
            self._mark_error(identity, envelope.error.detail or "Device rejected command")
            if self._pending and self._pending.envelope.message_id == identity:
                snapshot = self._pending.envelope.HasField("snapshot")
                self._pending = None
                if snapshot:
                    raise OSError("Device rejected recovery snapshot")
            return
        if not envelope.HasField("acknowledgment"):
            return
        ack = envelope.acknowledgment
        if ack.stage not in (pb.ACK_STAGE_ACCEPTED, pb.ACK_STAGE_PRESENTED):
            return
        if ack.stage == pb.ACK_STAGE_ACCEPTED:
            for key, delivery in self._deliveries.items():
                if key == ack.in_reply_to or key.startswith(ack.in_reply_to + ":"):
                    delivery.accepted = True
            if self._pending and self._pending.envelope.message_id == ack.in_reply_to:
                if self._pending.envelope.HasField("snapshot"):
                    self._state = "online"
                    self._last_error = None
                self._pending = None
        else:
            key = f"{ack.in_reply_to}:{ack.card_id}" if ack.card_id else ack.in_reply_to
            delivery = self._deliveries.get(key)
            if delivery is not None and delivery.accepted:
                if ack.card_id:
                    current = self._card_delivery.get(ack.card_id)
                    if current != (ack.revision, ack.in_reply_to):
                        return
                delivery.presented = True

    async def _retry_if_due(self) -> None:
        """Retry the current identity without extending notification validity.

        Raises
        ------
        TimeoutError
            If three transmissions received no UI acceptance.
        """
        pending = self._pending
        if pending is None or time.monotonic() - pending.sent_at < ACK_TIMEOUT_SECONDS:
            return
        if pending.expires_at is not None:
            remaining = int((pending.expires_at - time.monotonic()) * 1000)
            if remaining <= 0:
                self._mark_error(pending.envelope.message_id, "Notification expired")
                self._pending = None
                return
            pending.envelope.notification.valid_for_ms = remaining
        if pending.attempts >= MAX_SEND_ATTEMPTS:
            raise TimeoutError("UI Accepted acknowledgment timeout")
        pending.attempts += 1
        pending.sent_at = time.monotonic()
        await self._send(pending.envelope)
