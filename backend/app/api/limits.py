"""Per-user throttles for authenticated endpoints that are expensive or easy to abuse.

The auth endpoints already have per-IP limits (app/core/ratelimit.py). These are keyed by the signed-in user
instead, so one account cannot hammer a costly endpoint (the simulation lab, analytics queries, booking and
queue writes) and several users behind one office IP do not share a budget. Limits are deliberately generous:
they stop scripts and runaway clients, not people. Unauthenticated callers get 401 first (the dependency
authenticates before it counts), so anonymous traffic cannot fill a user's budget.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException

from app.api.deps import AuthContext, get_auth_context
from app.core.config import Settings, get_settings
from app.core.ratelimit import get_rate_limiter


def user_rate_limit(name: str, limit: int, window_seconds: int) -> Callable[..., None]:
    def dependency(ctx: AuthContext = Depends(get_auth_context), settings: Settings = Depends(get_settings)) -> None:
        if not settings.rate_limit_enabled:
            return
        allowed, retry_after = get_rate_limiter().hit(f"rl:user:{name}:{ctx.user.id}", limit, window_seconds)
        if not allowed:
            raise HTTPException(status_code=429, detail="Too many requests. Please try again later.",
                                headers={"Retry-After": str(retry_after)})

    return dependency


# One place to read and tune the budgets (requests per window, per user).
BOOKING = user_rate_limit("booking", 60, 300)
QUEUE_WRITE = user_rate_limit("queue_write", 300, 300)
ANALYTICS = user_rate_limit("analytics", 120, 300)
SIMULATION = user_rate_limit("simulation", 10, 300)
