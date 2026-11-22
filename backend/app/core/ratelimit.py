"""Fixed-window rate limiting with a Redis backend and an in-memory fallback.

If Redis is unreachable the limiter degrades to per-process memory counters rather than
failing open, so login throttling keeps working during a Redis outage.
"""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

import redis
from fastapi import Depends, HTTPException, Request

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""


class MemoryRateLimiter:
    def __init__(self, time_func: Callable[[], float] = time.monotonic) -> None:
        self._time = time_func
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = self._time()
        with self._lock:
            count, reset_at = self._buckets.get(key, (0, now + window_seconds))
            if now >= reset_at:
                count, reset_at = 0, now + window_seconds
            count += 1
            self._buckets[key] = (count, reset_at)
            if len(self._buckets) > 50_000:  # bound memory under key-spraying attacks
                self._buckets = {k: v for k, v in self._buckets.items() if v[1] > now}
            if count > limit:
                return False, max(1, int(reset_at - now))
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        self._fallback = MemoryRateLimiter()

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            if ttl < 0:
                self._client.expire(key, window_seconds)
                ttl = window_seconds
            if count > limit:
                return False, max(1, int(ttl))
            return True, 0
        except redis.RedisError:
            log.warning("rate limiter: Redis unavailable, using in-memory fallback")
            return self._fallback.hit(key, limit, window_seconds)


@lru_cache
def get_rate_limiter() -> RateLimiter:
    s = get_settings()
    use_redis = s.rate_limit_backend == "redis" or (s.rate_limit_backend == "auto" and s.redis_url)
    if use_redis and s.redis_url:
        return RedisRateLimiter(s.redis_url)
    return MemoryRateLimiter()


def get_client_ip(request: Request, settings: Settings) -> str | None:
    """Best-effort client IP. X-Forwarded-For is honoured only when TRUST_PROXY_HEADERS is set.
    Each trusted proxy appends the address it saw, so counting from the right is the only safe way: with TRUSTED_PROXY_HOPS=1 (one
    proxy, e.g. Caddy) the rightmost entry is used; with 2 (e.g. Vercel in front of Render) the one before it, which is the visitor.
    Entries further left can be forged by the client and are never used. A shorter chain than configured falls back to the peer address."""
    raw: str | None = None
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",")]
            hops = settings.trusted_proxy_hops
            if len(parts) >= hops:
                raw = parts[-hops]
    if raw is None and request.client:
        raw = request.client.host
    try:
        return str(ipaddress.ip_address(raw)) if raw else None
    except ValueError:
        return None


def rate_limit(name: str, limit: int, window_seconds: int) -> Callable[..., None]:
    """Dependency factory: limit requests per client IP for the named bucket."""

    def dependency(request: Request, settings: Settings = Depends(get_settings)) -> None:
        if not settings.rate_limit_enabled:
            return
        ip = get_client_ip(request, settings) or "unknown"
        allowed, retry_after = get_rate_limiter().hit(f"rl:{name}:{ip}", limit, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
