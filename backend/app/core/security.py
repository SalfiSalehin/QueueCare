"""Cryptographic primitives: password hashing, JWT access tokens, opaque tokens, CSRF tokens."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

JWT_ISSUER = "queuecare"
JWT_TYPE_ACCESS = "access"

# Argon2id with argon2-cffi defaults (RFC 9106 "low memory" profile).
_hasher = PasswordHasher(type=Type.ID)
# Verified against when an account does not exist, so response time doesn't reveal it.
_DUMMY_HASH = _hasher.hash("queuecare-dummy-password-for-timing")


def utcnow() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ------------------------------------------------------------- opaque tokens
def generate_opaque_token(nbytes: int = 48) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 of a high-entropy random token. Only the hash is ever stored."""
    return hashlib.sha256(token.encode()).hexdigest()


# ----------------------------------------------------------------------- JWT
@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, settings: Settings) -> tuple[str, datetime]:
    now = utcnow()
    expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "iss": JWT_ISSUER,
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": JWT_TYPE_ACCESS,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires


def decode_access_token(token: str, settings: Settings, *, verify_exp: bool = True) -> AccessClaims:
    """Validate signature, issuer, type and (by default) expiry. Raises jwt.PyJWTError."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],  # explicit allow-list: blocks alg=none / confusion
        issuer=JWT_ISSUER,
        options={"require": ["exp", "iat", "sub", "sid", "typ", "iss"], "verify_exp": verify_exp},
    )
    if payload.get("typ") != JWT_TYPE_ACCESS:
        raise jwt.InvalidTokenError("wrong token type")
    try:
        return AccessClaims(user_id=uuid.UUID(payload["sub"]), session_id=uuid.UUID(payload["sid"]))
    except (ValueError, TypeError) as exc:
        raise jwt.InvalidTokenError("malformed claims") from exc


# ---------------------------------------------------------------------- CSRF
# Token = "<session_id>.<nonce>.<hmac>". Double-submit: the same value is sent as a
# cookie and as the X-CSRF-Token header; the HMAC binds it to the session and our secret.
def _csrf_sig(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), f"csrf:{message}".encode(), hashlib.sha256).hexdigest()


def create_csrf_token(session_id: uuid.UUID | str, settings: Settings) -> str:
    nonce = secrets.token_urlsafe(16)
    return f"{session_id}.{nonce}.{_csrf_sig(settings.csrf_secret, f'{session_id}.{nonce}')}"


def parse_csrf_token(token: str | None, settings: Settings) -> str | None:
    """Return the session id embedded in a validly signed CSRF token, else None."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    sid, nonce, sig = parts
    if not hmac.compare_digest(sig, _csrf_sig(settings.csrf_secret, f"{sid}.{nonce}")):
        return None
    return sid


def tokens_equal(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())  # type: ignore[union-attr]
