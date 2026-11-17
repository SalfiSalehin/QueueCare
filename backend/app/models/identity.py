"""Identity, tenancy, session and audit models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Model, TimestampMixin


class Clinic(Model, TimestampMixin):
    __tablename__ = "clinics"

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(CITEXT, unique=True)
    timezone: Mapped[str] = mapped_column(Text, server_default="UTC")
    status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class User(Model, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    platform_role: Mapped[str] = mapped_column(Text, server_default="NONE")
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClinicMembership(Model, TimestampMixin):
    __tablename__ = "clinic_memberships"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class UserSession(Model, TimestampMixin):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Model, TimestampMixin):
    __tablename__ = "refresh_tokens"

    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sessions.id"))
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OneTimeToken(Model, TimestampMixin):
    """Single-use tokens for password reset and email verification (stored hashed)."""

    __tablename__ = "one_time_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Model):
    """Append-only (no updated_at; the app DB role has no UPDATE/DELETE)."""

    __tablename__ = "audit_logs"

    clinic_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
