"""Envelope construction and defensive feedback decoding."""

from uuid import uuid4

from google.protobuf.message import DecodeError

from info_tv_service.device.generated import device_pb2 as pb


def make_envelope(session_id: str) -> pb.Envelope:
    """Create an operation identity.

    Parameters
    ----------
    session_id : str
        Current service process identity, empty only for discovery.

    Returns
    -------
    Envelope
        Versioned envelope without an operation body.
    """
    return pb.Envelope(protocol_version=1, session_id=session_id, message_id=uuid4().hex)


def decode_feedback(payload: bytes) -> pb.Envelope | None:
    """Parse structurally supported device feedback.

    Parameters
    ----------
    payload : bytes
        Verified frame payload.

    Returns
    -------
    Envelope or None
        Valid feedback envelope, otherwise None.
    """
    message = pb.Envelope()
    try:
        message.ParseFromString(payload)
    except DecodeError:
        return None
    if message.protocol_version != 1 or not 0 < len(message.message_id) <= 36:
        return None
    if message.WhichOneof("body") not in ("hello", "acknowledgment", "error", "pong"):
        return None
    return message
