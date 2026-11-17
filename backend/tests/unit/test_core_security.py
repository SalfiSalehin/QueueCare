"""Pure unit tests (no database needed beyond the shared fixtures)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core import security
from app.core.config import Settings
from app.core.logging import redact
from app.core.ratelimit import MemoryRateLimiter
from app.schemas.auth import validate_password_strength

BASE = dict(
    database_url="postgresql+psycopg://u:p@h/db",
    jwt_secret="j" * 40,
    csrf_secret="c" * 40,
)


def settings(**over) -> Settings:
    return Settings(_env_file=None, **{**BASE, **over})


# ------------------------------------------------------------------ passwords
def test_password_uses_argon2id_and_verifies():
    h = security.hash_password("Correct-Horse-Battery-9")
    assert h.startswith("$argon2id$")
    assert security.verify_password(h, "Correct-Horse-Battery-9")
    assert not security.verify_password(h, "wrong")
    assert not security.verify_password("not-a-hash", "x")


def test_password_policy():
    for bad in ("short", "a" * 20, "password12345", "   " * 6):
        with pytest.raises(ValueError):
            validate_password_strength(bad)
    with pytest.raises(ValueError):
        validate_password_strength("my-alice-secret-1", email="alice@example.com")
    assert validate_password_strength("Correct-Horse-Battery-9")


# ------------------------------------------------------------------------ JWT
def test_jwt_roundtrip_and_tamper():
    s = settings()
    uid, sid = uuid.uuid4(), uuid.uuid4()
    token, _ = security.create_access_token(uid, sid, s)
    claims = security.decode_access_token(token, s)
    assert (claims.user_id, claims.session_id) == (uid, sid)
    with pytest.raises(jwt.PyJWTError):
        security.decode_access_token(token[:-2] + "xx", s)
    with pytest.raises(jwt.PyJWTError):
        security.decode_access_token(token, settings(jwt_secret="z" * 40))


def test_jwt_rejects_expired_none_alg_and_wrong_type():
    s = settings()
    now = datetime.now(UTC)
    base = {"iss": "queuecare", "sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()), "typ": "access", "iat": now}
    expired = jwt.encode({**base, "exp": now - timedelta(minutes=1)}, s.jwt_secret, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_access_token(expired, s)
    none_alg = jwt.encode({**base, "exp": now + timedelta(minutes=5)}, None, algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        security.decode_access_token(none_alg, s)
    wrong_type = jwt.encode({**base, "typ": "refresh", "exp": now + timedelta(minutes=5)}, s.jwt_secret)
    with pytest.raises(jwt.PyJWTError):
        security.decode_access_token(wrong_type, s)


# ----------------------------------------------------------------------- CSRF
def test_csrf_token_binding_and_tamper():
    s = settings()
    sid = uuid.uuid4()
    t = security.create_csrf_token(sid, s)
    assert security.parse_csrf_token(t, s) == str(sid)
    assert security.parse_csrf_token(t + "x", s) is None
    assert security.parse_csrf_token(None, s) is None
    assert security.parse_csrf_token(t, settings(csrf_secret="d" * 40)) is None
    assert security.parse_csrf_token("a.b", s) is None


def test_token_hashing_is_deterministic_and_not_plaintext():
    t = security.generate_opaque_token()
    assert security.hash_token(t) == security.hash_token(t) != t
    assert len(t) >= 48


# --------------------------------------------------------------------- config
@pytest.mark.parametrize("over", [
    {"jwt_secret": "CHANGE_ME_64_BYTE_RANDOM_SECRET_PLACEHOLDER_XXXX"},
    {"jwt_secret": "short"},
    {"csrf_secret": "j" * 40},                       # same as JWT secret
    {"backend_cors_origins": "*"},
    {"backend_cors_origins": ""},
    {"cookie_samesite": "none", "cookie_secure": False},
    {"database_url": "postgresql://u:CHANGE_ME@h/db"},
])
def test_config_rejects_unsafe_values(over):
    with pytest.raises(ValidationError):
        settings(**over)


def test_config_production_rules():
    with pytest.raises(ValidationError):
        settings(app_env="production", cookie_secure=False)
    with pytest.raises(ValidationError):
        settings(app_env="production", cookie_secure=True, backend_cors_origins="http://app.example.com")
    ok = settings(app_env="production", cookie_secure=True, backend_cors_origins="https://app.example.com")
    assert ok.is_production


# ---------------------------------------------------------------- misc units
def test_log_redaction():
    out = redact('login password=hunter2 token: abc123 Authorization=Bearer')
    assert "hunter2" not in out and "abc123" not in out and "[REDACTED]" in out


def test_memory_rate_limiter_window():
    now = [0.0]
    rl = MemoryRateLimiter(time_func=lambda: now[0])
    assert [rl.hit("k", 3, 60)[0] for _ in range(4)] == [True, True, True, False]
    assert rl.hit("other", 3, 60)[0] is True          # independent keys
    now[0] = 61.0
    assert rl.hit("k", 3, 60)[0] is True               # window reset
