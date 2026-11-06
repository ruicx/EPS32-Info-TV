"""Application-owned composition and supervised device task lifecycle."""

import asyncio
import logging

from info_tv_service.config import Settings
from info_tv_service.device.serial_transport import SerialTransport
from info_tv_service.device.session import DeviceSession
from info_tv_service.device.transport import ByteTransport
from info_tv_service.tasks.service import TaskService
from info_tv_service.tasks.store import TaskStore
from info_tv_service.weather import WeatherUpdater


class ServiceRuntime:
    """Own all mutable state for one FastAPI application instance."""

    def __init__(self, settings: Settings, transport: ByteTransport | None = None) -> None:
        """Compose state and device services without opening external resources.

        Parameters
        ----------
        settings : Settings
            Immutable application configuration.
        transport : ByteTransport or None
            Test seam; production creates the configured serial transport.
        """
        self.store = TaskStore()
        self.device = DeviceSession(transport or SerialTransport(settings.serial_port), self.store.list_tasks)
        self.tasks = TaskService(self.store, self.device, settings.completed_retention_seconds)
        self.weather = WeatherUpdater(settings.weather, self.device) if settings.weather is not None else None
        self.failure: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None
        self._weather_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the lifespan-owned device coordinator."""
        self._task = asyncio.create_task(self.device.run(), name="info-tv-device")
        self._task.add_done_callback(self._task_done)
        self._maintenance_task = asyncio.create_task(self._maintain_tasks(), name="info-tv-retention")
        self._maintenance_task.add_done_callback(self._task_done)
        if self.weather is not None:
            self._weather_task = asyncio.create_task(self.weather.run(), name="info-tv-weather")
            self._weather_task.add_done_callback(self._task_done)

    async def _maintain_tasks(self) -> None:
        """Expire completed cards even when no producer sends further events."""
        while True:
            self.tasks.expire_completed()
            await asyncio.sleep(1)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        """Report an unexpected coordinator failure immediately.

        Parameters
        ----------
        task : Task
            Completed device coordinator.
        """
        if not task.cancelled():
            error = task.exception()
            self.failure = f"{task.get_name()}: {error or 'Background task unexpectedly exited'}"
            logging.getLogger(__name__).error("Background task failed: %s", self.failure)

    async def stop(self) -> None:
        """Cancel and await background work and transport cleanup."""
        tasks = [task for task in (self._task, self._maintenance_task, self._weather_task) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
