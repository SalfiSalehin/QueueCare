"""Uniform, safe error responses. Never leaks stack traces, SQL, or submitted values."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
    409: "conflict", 413: "payload_too_large", 422: "validation_error", 429: "rate_limited",
    500: "internal_error", 503: "service_unavailable",
}


class ServiceError(Exception):
    """A business-rule failure with a client-safe message and HTTP status (404, 409, 422, ...)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_body(status: int, message: str, request: Request, details: list[dict[str, str]] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": {"code": _CODES.get(status, "error"), "message": message, "request_id": request_id_of(request)}
    }
    if details:
        body["error"]["details"] = details
    return body


class ApiError(Exception):
    """Domain error raised by services; rendered with the uniform error body.
    `message` must be safe to show to clients."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.status_code, exc.message, request), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(error_body(exc.status_code, message, request), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(ServiceError)
    async def _service(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(error_body(exc.status, exc.message, request), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Deliberately omit `input` / `ctx`: submitted values may be passwords.
        details = [
            {
                "field": ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path")),
                "message": str(err["msg"]).removeprefix("Value error, "),
            }
            for err in exc.errors()
        ]
        return JSONResponse(error_body(422, "Invalid request.", request, details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"request_id": request_id_of(request)})
        return JSONResponse(error_body(500, "Internal server error.", request), status_code=500)
