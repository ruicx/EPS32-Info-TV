"""Stream corruption and resynchronization tests."""

import pytest

from info_tv_service.device.framing import FrameDecoder, encode_frame


def test_chunking_concatenation_and_noise_recovery() -> None:
    """No read boundary is assumed and boot noise cannot poison later frames."""
    decoder = FrameDecoder()
    stream = b"ROM boot text\r\n" + encode_frame(bytes(range(256))) + encode_frame(b"next\0message")
    result: list[bytes] = []
    for offset in range(0, len(stream), 7):
        result.extend(decoder.feed(stream[offset:offset + 7]))
    assert result == [bytes(range(256)), b"next\0message"]


def test_crc_oversize_truncation_and_recovery() -> None:
    """Damaged or excessive input is discarded, then a valid frame survives."""
    valid = encode_frame(b"verified")
    damaged = bytearray(encode_frame(b"bad"))
    damaged[2] ^= 0x10
    decoder = FrameDecoder()
    stream = bytes(damaged) + b"\x01" * 5000 + b"\0" + valid[:3] + b"\0" + valid
    assert decoder.feed(stream) == [b"verified"]
    assert FrameDecoder().feed(encode_frame(bytes(range(256)) * 16)) == [bytes(range(256)) * 16]
    with pytest.raises(ValueError):
        encode_frame(b"x" * 4097)
