"""Short-lived, single-use WebSocket tickets.

Browsers cannot attach an Authorization header to a WebSocket, and we do not want long-lived
credentials in a URL. So an authenticated, CSRF-protected REST call mints a ticket that:
  - lives 30 seconds (default),
  - is bound to one user, one clinic and one login session,
  - can be redeemed once (replays are rejected),
  - is signed with a key derived from JWT_SECRET but different from the access-token key, so an
    access token is never valid as a ticket and a ticket is never valid as an access token.

The ticket proves identity only. Role and channels are re-derived from the database at connect time.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
import uuid
from dataclasses import dataclass

import jwt

log = logging.getLogger("queuecare.ws")

AUDIENCE = "queuecare-ws"
ISSUER = "queuecare"


class TicketError(Exception):
    pass


@dataclass(frozen=True)
class TicketClaims:
    user_id: uuid.UUID
    clinic_id: uuid.UUID
    session_id: uuid.UUID
    jti: str


def _key(jwt_secret: str) -> str:
    return hmac.new(jwt_secret.encode(), b"queuecare-ws-ticket-v1", hashlib.sha256).hexdigest()


def issue_ticket(
    jwt_secret: str, algorithm: str, *, user_id: uuid.UUID, clinic_id: uuid.UUID, session_id: uuid.UUID,
    ttl_seconds: int, now: float | None = None,
) -> str:
    issued = int(now if now is not None else time.time())
    return jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": str(user_id), "cid": str(clinic_id), "sid": str(session_id),
         "jti": uuid.uuid4().hex, "iat": issued, "exp": issued + ttl_seconds},
        _key(jwt_secret), algorithm=algorithm,
    )


def verify_ticket(jwt_secret: str, algorithm: str, token: str) -> TicketClaims:
    try:
        claims = jwt.decode(
            token, _key(jwt_secret), algorithms=[algorithm], audience=AUDIENCE, issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "cid", "sid", "jti"]},
        )
        return TicketClaims(uuid.UUID(claims["sub"]), uuid.UUID(claims["cid"]), uuid.UUID(claims["sid"]),
                            str(claims["jti"]))
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise TicketError("invalid ticket") from None


# ------------------------------------------------------------- single use
class MemoryTicketStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def consume(self, jti: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if v > now}
            if jti in self._seen:
                return False
            self._seen[jti] = now + ttl_seconds
            return True


class RedisTicketStore:
    def __init__(self, url: str) -> None:
        import redis

        self._redis_error = redis.RedisError
        self._client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        self._fallback = MemoryTicketStore()

    def consume(self, jti: str, ttl_seconds: int) -> bool:
        try:
            return bool(self._client.set(f"qc:ws:jti:{jti}", "1", nx=True, ex=ttl_seconds))
        except self._redis_error:
            log.warning("ws tickets: Redis unavailable, using in-memory single-use check")
            return self._fallback.consume(jti, ttl_seconds)


_stores: dict[str, object] = {}
_stores_lock = threading.Lock()


def get_ticket_store(redis_url: str | None):  # type: ignore[no-untyped-def]
    key = redis_url or ""
    with _stores_lock:
        if key not in _stores:
            _stores[key] = RedisTicketStore(redis_url) if redis_url else MemoryTicketStore()
        return _stores[key]
