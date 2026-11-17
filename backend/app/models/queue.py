"""Live queue: tokens, the per-day token counter, the append-only event log, consultations."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Model, TimestampMixin


class QueueCounter(Base, TimestampMixin):
    """Last token number handed out per clinic/day/prefix. Incremented with a single atomic
    INSERT ... ON CONFLICT DO UPDATE, so two requests can never receive the same number."""

    __tablename__ = "queue_counters"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"), primary_key=True)
    queue_date: Mapped[date] = mapped_column(Date, primary_key=True)
    prefix: Mapped[str] = mapped_column(Text, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)


class QueueToken(Model, TimestampMixin):
    __tablename__ = "queue_tokens"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("doctors.id"))
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("patients.id"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("appointments.id"))
    queue_date: Mapped[date] = mapped_column(Date)            # clinic-local date of arrival
    prefix: Mapped[str] = mapped_column(Text)
    sequence_no: Mapped[int] = mapped_column(Integer)
    token_label: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)                  # WALK_IN | APPOINTMENT
    status: Mapped[str] = mapped_column(Text, default="WAITING")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(BigInteger, default=1)


class QueueTokenEvent(Model):
    """Append-only (the application role has no UPDATE/DELETE). Feeds analytics and ML later."""

    __tablename__ = "queue_token_events"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    token_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("queue_tokens.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Consultation(Model, TimestampMixin):
    __tablename__ = "consultations"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    token_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("queue_tokens.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("doctors.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_wait_minutes: Mapped[int | None] = mapped_column(Integer)
