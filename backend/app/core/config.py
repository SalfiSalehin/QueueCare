"""Application settings, loaded from environment variables and validated at startup.

The app refuses to start with placeholder, short, or duplicated secrets, and enforces
stricter rules when APP_ENV=production. Nothing here has a default for a secret.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ORIGIN_RE = re.compile(r"^https?://[^/\s]+$")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # General
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    demo_mode: bool = True

    # Database / cache (no defaults: must be provided)
    database_url: str
    migration_database_url: str | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 10
    redis_url: str | None = None

    # Auth
    jwt_secret: str
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    csrf_secret: str
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    session_absolute_max_days: int = 30
    refresh_reuse_grace_seconds: int = 5
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    password_reset_ttl_minutes: int = 30
    email_verify_ttl_hours: int = 48

    # HTTP
    backend_cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"
    max_request_body_bytes: int = 1_048_576
    trust_proxy_headers: bool = False
    trusted_proxy_hops: int = Field(default=1, ge=1, le=5)   # how many proxies append to X-Forwarded-For before the API (Caddy alone: 1)

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_backend: Literal["auto", "redis", "memory"] = "auto"

    # ML wait-time model (trained offline by `python -m ml.training.run`; promoted with ml.training.promote)
    ml_model_dir: str = "/app/ml/models"

    # Real-time (outbox relay + WebSocket gateway)
    outbox_relay_enabled: bool = True
    outbox_poll_interval_seconds: float = 0.5
    outbox_batch_size: int = 100
    outbox_retention_days: int = 7
    ws_ticket_ttl_seconds: int = 30
    ws_idle_timeout_seconds: int = 90
    ws_revalidate_seconds: int = 300
    ws_max_connections_per_user: int = 5
    ws_max_connections_per_ip: int = 50

    # Notifications
    email_provider: Literal["mock"] = "mock"
    notification_worker_enabled: bool = True
    notification_poll_interval_seconds: float = 2.0
    notification_batch_size: int = 50
    notification_max_attempts: int = 5
    notification_backoff_base_seconds: int = 30       # retry delays: 30s, 60s, 120s, 240s (capped at 1h)
    notification_lease_seconds: int = 120             # a claimed row is not re-claimed before this elapses
    notification_reminder_hours: int = 24             # appointment reminder lead time
    notification_retention_days: int = 30

    @field_validator("cookie_domain", "redis_url", "migration_database_url", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _validate_security(self) -> Settings:
        for name in ("jwt_secret", "csrf_secret"):
            value = getattr(self, name)
            if "CHANGE_ME" in value or len(value) < 32:
                raise ValueError(f"{name.upper()} must be a random value of at least 32 characters")
        if self.jwt_secret == self.csrf_secret:
            raise ValueError("JWT_SECRET and CSRF_SECRET must be different values")
        if "CHANGE_ME" in self.database_url or (self.redis_url and "CHANGE_ME" in self.redis_url):
            raise ValueError("Replace CHANGE_ME placeholders in DATABASE_URL / REDIS_URL")

        origins = self.cors_origins
        if not origins:
            raise ValueError("BACKEND_CORS_ORIGINS must list at least one explicit origin")
        for origin in origins:
            if origin == "*" or not _ORIGIN_RE.match(origin):
                raise ValueError(f"Invalid CORS origin {origin!r}: use explicit scheme://host[:port]")

        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")

        if self.is_production:
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            insecure = [o for o in origins if o.startswith("http://") and not any(h in o for h in _LOCAL_HOSTS)]
            if insecure:
                raise ValueError("Production CORS origins must use https://")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
