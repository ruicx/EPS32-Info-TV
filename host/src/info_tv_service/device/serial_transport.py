"""Portable pySerial transport with a single owned blocking-I/O thread."""

import asyncio
import queue
import threading

import serial


class SerialTransport:
    """Keep blocking serial I/O and port ownership outside the event loop."""

    def __init__(self, port: str) -> None:
        """Configure the transport without opening the port.

        Parameters
        ----------
        port : str
            Platform-specific serial device path.
        """
        self._port = port
        self._incoming: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
        self._outgoing: queue.Queue[bytes] = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready: asyncio.Future[None] | None = None
        self._failure: OSError | None = None

    async def open(self) -> None:
        """Start the worker and await successful port opening.

        Raises
        ------
        OSError
            If the port cannot be opened.
        """
        self._incoming = asyncio.Queue(maxsize=8)
        self._outgoing = queue.Queue(maxsize=8)
        self._failure = None
        self._stop.clear()
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._thread = threading.Thread(target=self._worker, args=(loop,), name="info-tv-serial", daemon=True)
        self._thread.start()
        await self._ready

    def _opened(self) -> None:
        """Complete the opening future on its owning event loop."""
        if self._ready is not None and not self._ready.done():
            self._ready.set_result(None)

    def _failed(self, reason: str) -> None:
        """Report a worker failure on the event loop.

        Parameters
        ----------
        reason : str
            Underlying serial error or handoff overflow.
        """
        self._failure = OSError(reason)
        self._stop.set()
        if self._ready is not None and not self._ready.done():
            self._ready.set_exception(self._failure)

    def _offer(self, data: bytes) -> None:
        """Admit a received chunk without unbounded buffering.

        Parameters
        ----------
        data : bytes
            Worker-owned received bytes.
        """
        try:
            self._incoming.put_nowait(data)
        except asyncio.QueueFull:
            self._failed("Serial receive handoff overflow")

    def _worker(self, loop: asyncio.AbstractEventLoop) -> None:
        """Own the serial handle until shutdown.

        Parameters
        ----------
        loop : AbstractEventLoop
            Owning event loop for bounded result delivery.
        """
        connection = serial.Serial(port=None, baudrate=115200, timeout=0.05, write_timeout=0.5)
        try:
            connection.dtr = False
            connection.rts = False
            connection.port = self._port
            connection.open()
            connection.reset_input_buffer()
            loop.call_soon_threadsafe(self._opened)
            while not self._stop.is_set():
                try:
                    outgoing = self._outgoing.get_nowait()
                except queue.Empty:
                    outgoing = b""
                if outgoing:
                    offset = 0
                    while offset < len(outgoing):
                        written = connection.write(outgoing[offset:])
                        if written is None or written <= 0:
                            raise OSError("Serial write made no progress")
                        offset += written
                chunk = connection.read(max(1, min(connection.in_waiting, 4096)))
                if chunk:
                    loop.call_soon_threadsafe(self._offer, chunk)
        except (OSError, serial.SerialException) as error:
            loop.call_soon_threadsafe(self._failed, str(error))
        finally:
            connection.close()

    async def read(self) -> bytes:
        """Await received bytes, observing worker failure promptly.

        Returns
        -------
        bytes
            Nonempty stream chunk.

        Raises
        ------
        OSError
            If the worker failed.
        """
        while True:
            if self._failure is not None:
                raise self._failure
            try:
                return await asyncio.wait_for(self._incoming.get(), timeout=0.1)
            except TimeoutError:
                continue

    async def write(self, data: bytes) -> None:
        """Queue bytes without blocking the event loop.

        Parameters
        ----------
        data : bytes
            Complete ordered output chunk.

        Raises
        ------
        OSError
            If disconnected or the outbound queue is full.
        """
        if self._failure is not None:
            raise self._failure
        try:
            self._outgoing.put_nowait(data)
        except queue.Full as error:
            raise OSError("Serial transmit handoff overflow") from error

    async def close(self) -> None:
        """Stop and join the worker before another session can open the port.

        Raises
        ------
        OSError
            If bounded serial timeouts did not allow worker termination.
        """
        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 2)
            if self._thread.is_alive():
                raise OSError("Serial worker did not terminate")
            self._thread = None
