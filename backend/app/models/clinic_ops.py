"""Clinic operations models: departments, doctors, weekly schedules, time off."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, ForeignKey, Integer, SmallInteger, Text, Time, text
from sqlalchemy.dialects.postgresql import TSTZRANGE, Range
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Model, TimestampMixin


class Department(Model, TimestampMixin):
    __tablename__ = "departments"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    name: Mapped[str] = mapped_column(Text)
    queue_prefix: Mapped[str] = mapped_column(Text)


class Doctor(Model, TimestampMixin):
    __tablename__ = "doctors"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    department_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("departments.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    display_name: Mapped[str] = mapped_column(Text)
    default_slot_minutes: Mapped[int] = mapped_column(Integer, server_default=text("15"))
    buffer_minutes: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    status: Mapped[str] = mapped_column(Text, server_default="AVAILABLE")
    current_delay_minutes: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class DoctorSchedule(Model, TimestampMixin):
    """Recurring weekly availability window. day_of_week: 0 = Monday ... 6 = Sunday.
    Times are wall-clock in the clinic's timezone."""

    __tablename__ = "doctor_schedules"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("doctors.id"))
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    valid_from: Mapped[date | None] = mapped_column(Date)  # NULL = open-ended
    valid_to: Mapped[date | None] = mapped_column(Date)


class DoctorTimeOff(Model, TimestampMixin):
    __tablename__ = "doctor_time_off"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("doctors.id"))
    period: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    reason: Mapped[str | None] = mapped_column(Text)
