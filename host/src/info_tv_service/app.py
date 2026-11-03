"""FastAPI application factory and resource lifecycle."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from info_tv_service.api.routes import create_router
from info_tv_service.config import Settings
from info_tv_service.device.transport import ByteTransport
from info_tv_service.runtime import ServiceRuntime


def create_app(settings: Settings, transport: ByteTransport | None = None) -> FastAPI:
    """Build an isolated application instance.

    Parameters
    ----------
    settings : Settings
        Service configuration.
    transport : ByteTransport or None
        Optional device transport for integration tests.

    Returns
    -------
    FastAPI
        Application whose lifespan owns all mutable service state.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Own resources for exactly one application lifetime.

        Parameters
        ----------
        app : FastAPI
            Application receiving its runtime context.

        Yields
        ------
        None
            Control while serving requests.
        """
        runtime = ServiceRuntime(settings, transport)
        app.state.runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="info_tv", lifespan=lifespan)
    app.include_router(create_router())
    return app
