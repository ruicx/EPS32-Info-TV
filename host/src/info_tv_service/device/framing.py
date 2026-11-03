"""Bounded COBS frames with CRC32-IEEE and zero-byte resynchronization."""

import struct
import zlib

MAX_PAYLOAD = 4096
MAX_ENCODED = 4120


def encode_frame(payload: bytes) -> bytes:
    """Encode a payload, including leading and trailing synchronization bytes.

    Parameters
    ----------
    payload : bytes
        Serialized Protobuf payload.

    Returns
    -------
    bytes
        COBS payload and little-endian CRC, surrounded by zero delimiters.

    Raises
    ------
    ValueError
        If the payload is empty or exceeds 4096 bytes.
    """
    if not 0 < len(payload) <= MAX_PAYLOAD:
        raise ValueError("Invalid payload size")
    raw = payload + struct.pack("<I", zlib.crc32(payload))
    encoded = bytearray([0])
    index, code = 0, 1
    for value in raw:
        if value == 0:
            encoded[index] = code
            index = len(encoded)
            encoded.append(0)
            code = 1
        else:
            encoded.append(value)
            code += 1
            if code == 255:
                encoded[index] = code
                index = len(encoded)
                encoded.append(0)
                code = 1
    encoded[index] = code
    return b"\0" + bytes(encoded) + b"\0"


def decode_frame(encoded: bytes) -> bytes | None:
    """Validate one delimiter-free frame.

    Parameters
    ----------
    encoded : bytes
        One bounded COBS body.

    Returns
    -------
    bytes or None
        Verified payload, or None for malformed or corrupted content.
    """
    raw = bytearray()
    index = 0
    while index < len(encoded):
        code = encoded[index]
        index += 1
        if code == 0 or index + code - 1 > len(encoded):
            return None
        raw.extend(encoded[index:index + code - 1])
        index += code - 1
        if code != 255 and index < len(encoded):
            raw.append(0)
    if not 4 < len(raw) <= MAX_PAYLOAD + 4:
        return None
    payload = bytes(raw[:-4])
    return payload if zlib.crc32(payload) == struct.unpack("<I", raw[-4:])[0] else None


class FrameDecoder:
    """Collect partial frames with bounded storage and delimiter recovery."""

    def __init__(self) -> None:
        """Initialize an empty receive buffer."""
        self._buffer = bytearray()
        self._discard = False

    def reset(self) -> None:
        """Discard partial data after a connection boundary."""
        self._buffer.clear()
        self._discard = False

    def feed(self, chunk: bytes) -> list[bytes]:
        """Process an arbitrary stream chunk.

        Parameters
        ----------
        chunk : bytes
            Partial, complete, or multiple frames.

        Returns
        -------
        list[bytes]
            Complete verified payloads in order.
        """
        result: list[bytes] = []
        for value in chunk:
            if value == 0:
                if self._buffer and not self._discard:
                    decoded = decode_frame(bytes(self._buffer))
                    if decoded is not None:
                        result.append(decoded)
                self.reset()
            elif not self._discard:
                self._buffer.append(value)
                if len(self._buffer) > MAX_ENCODED:
                    self._buffer.clear()
                    self._discard = True
        return result
