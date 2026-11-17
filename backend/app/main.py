"""QueueCare API application factory."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.database import dispose_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.websocket.broker import get_broker
from app.websocket.hub import Hub
from app.workers.notification_worker import notification_loop
from app.workers.outbox_relay import relay_loop
from app.middleware.asgi import BodySizeLimitMiddleware, RequestIdMiddleware, SecurityHeadersMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    hub = Hub(max_per_user=settings.ws_max_connections_per_user, max_per_ip=settings.ws_max_connections_per_ip)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        broker = get_broker(settings.redis_url)
        hub.ensure_attached(broker)
        relay = asyncio.create_task(relay_loop(settings, broker)) if settings.outbox_relay_enabled else None
        notifier = asyncio.create_task(notification_loop(settings)) if settings.notification_worker_enabled else None
        try:
            yield
        finally:
            if notifier is not None:
                notifier.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await notifier
            if relay is not None:
                relay.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await relay
            hub.detach()
            dispose_engine()  # graceful shutdown: release pooled connections

    docs = not settings.is_production
    app = FastAPI(
        title="QueueCare API",
        version="0.2.0",
        description="Demonstration system. Synthetic data only.",
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
        debug=False,  # never enable Starlette debug tracebacks
        lifespan=lifespan,
    )

    app.state.hub = hub
    register_exception_handlers(app)

    # Middleware order: the LAST added is the OUTERMOST.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Authorization"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app() if __name__ != "__main__" else None  # type: ignore[assignment]
