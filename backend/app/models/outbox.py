"""Transactional outbox: events written in the same transaction as the change that caused them."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Model, TimestampMixin


class OutboxEvent(Model, TimestampMixin):
    __tablename__ = "outbox_events"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    channel: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Assigned by the database sequence at INSERT time (see ordering note in docs/realtime.md).
    version: Mapped[int] = mapped_column(BigInteger, server_default=text("nextval('outbox_version_seq')"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
