"""Patients (a person's profile WITHIN one clinic) and appointments."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Model, TimestampMixin


class Patient(Model, TimestampMixin):
    """Per-clinic patient profile. user_id is NULL for walk-ins registered by staff.
    A person who uses two clinics has two unrelated profiles (tenant isolation)."""

    __tablename__ = "patients"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    full_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Appointment(Model, TimestampMixin):
    """starts_at/ends_at are UTC. ends_at INCLUDES the doctor's buffer (it is the occupied range
    protected by the database exclusion constraint), so it is later than the consultation end."""

    __tablename__ = "appointments"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("doctors.id"))
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("patients.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    rescheduled_from: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))  # no ORM FK: self-reference
    cancel_reason: Mapped[str | None] = mapped_column(Text)
