from __future__ import annotations

import logging

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_engine

router = APIRouter(prefix="/health", tags=["health"])
log = logging.getLogger(__name__)


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response) -> dict[str, str]:
    """Readiness: database must answer. Redis is optional (degrades to in-memory limits)."""
    checks = {"database": "ok", "redis": "disabled"}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - report only a generic status
        log.warning("readiness: database check failed")
        checks["database"] = "unavailable"
    url = get_settings().redis_url
    if url:
        try:
            import redis
            redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5).ping()
            checks["redis"] = "ok"
        except Exception:  # noqa: BLE001
            checks["redis"] = "unavailable"
    healthy = checks["database"] == "ok"
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", **checks}
