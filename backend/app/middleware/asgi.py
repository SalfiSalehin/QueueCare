"""Pure-ASGI middleware: request IDs, security headers, request body size limit.

Pure ASGI (not BaseHTTPMiddleware) keeps streaming/WebSocket behaviour correct.
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_DOC_PREFIXES = ("/docs", "/redoc", "/openapi.json")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        await self.app(scope, receive, send_with_id)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope["path"].startswith(_DOC_PREFIXES)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cross-origin-resource-policy": b"same-site",
                }
                if not is_docs:
                    extra[b"content-security-policy"] = b"default-src 'none'; frame-ancestors 'none'"
                    extra[b"cache-control"] = b"no-store"  # API responses may be user-specific
                if self.hsts:
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                headers.extend((k, v) for k, v in extra.items() if k not in present)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject requests whose body exceeds max_bytes (checks Content-Length and the stream)."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        body = json.dumps(
            {"error": {"code": "payload_too_large", "message": "Request body too large.", "request_id": request_id}}
        ).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length and length.isdigit() and int(length) > self.max_bytes:
            await self._reject(scope, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(scope, send)
