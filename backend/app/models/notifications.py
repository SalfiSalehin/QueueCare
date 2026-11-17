"""Notification rows (table from migration 0001). One row per (event, recipient, channel)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Model, TimestampMixin


class Notification(Model, TimestampMixin):
    __tablename__ = "notifications"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(Text)               # EMAIL | SMS | IN_APP
    type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="PENDING")    # PENDING | SENT | FAILED | READ
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
