"""Async byte transport boundary, independent of framing and business state."""

from typing import Protocol


class ByteTransport(Protocol):
    """Provide one ordered duplex byte stream owned by a device session."""

    async def open(self) -> None:
        """Open the stream.

        Raises
        ------
        OSError
            If the device cannot be opened.
        """
        ...

    async def read(self) -> bytes:
        """Wait for stream data.

        Returns
        -------
        bytes
            A nonempty chunk, not necessarily a complete message.

        Raises
        ------
        OSError
            If the stream fails or its bounded handoff overflows.
        """
        ...

    async def write(self, data: bytes) -> None:
        """Submit bytes for ordered transmission.

        Parameters
        ----------
        data : bytes
            Bytes owned by the caller, copied or retained safely by the transport.

        Raises
        ------
        OSError
            If the connection or bounded outbound queue fails.
        """
        ...

    async def close(self) -> None:
        """Close the stream and release owned I/O resources."""
        ...
