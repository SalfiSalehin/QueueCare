"""Request/response schemas for clinic operations (Phase 3): departments, doctors, schedules, time off.

Clinic settings and member schemas live in app/schemas/clinic.py.
All request models forbid unknown fields, which blocks mass assignment (e.g. a client
cannot smuggle clinic_id, status or is_active into a create call).
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.permissions.roles import DoctorStatus
from app.schemas.common import StrictModel

MAX_TIME_OFF_DAYS = 90
PREFIX_PATTERN = r"^[A-Z]{1,3}$"


# --------------------------------------------------------------- departments
class DepartmentCreate(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    queue_prefix: str = Field(pattern=PREFIX_PATTERN, description="1-3 letters used in queue tokens, e.g. 'G' -> G-001")

    @field_validator("queue_prefix", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class DepartmentUpdate(StrictModel):
    """Only the name can change. The prefix is baked into issued tokens, so it is immutable."""

    name: str = Field(min_length=2, max_length=100)


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    queue_prefix: str


# ------------------------------------------------------------------- doctors
class DoctorCreate(StrictModel):
    display_name: str = Field(min_length=2, max_length=120)
    department_id: uuid.UUID
    default_slot_minutes: int = Field(default=15, ge=5, le=240)
    buffer_minutes: int = Field(default=5, ge=0, le=120)
    user_id: uuid.UUID | None = Field(
        default=None, description="Optional: link to an existing DOCTOR member of this clinic")


class DoctorUpdate(StrictModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    department_id: uuid.UUID | None = None
    default_slot_minutes: int | None = Field(default=None, ge=5, le=240)
    buffer_minutes: int | None = Field(default=None, ge=0, le=120)
    is_active: bool | None = None


class DoctorStatusUpdate(StrictModel):
    status: DoctorStatus
    current_delay_minutes: int = Field(default=0, ge=0, le=480)

    @model_validator(mode="after")
    def _delay_only_when_delayed(self) -> DoctorStatusUpdate:
        if self.current_delay_minutes and self.status != DoctorStatus.DELAYED:
            raise ValueError("current_delay_minutes can only be set when status is DELAYED")
        return self


class DoctorOut(BaseModel):
    """Public-safe view: exposes whether an account is linked, never the account's id or email."""

    id: uuid.UUID
    department_id: uuid.UUID
    display_name: str
    default_slot_minutes: int
    buffer_minutes: int
    status: str
    current_delay_minutes: int
    is_active: bool
    has_account: bool

    @classmethod
    def from_model(cls, d: Any) -> DoctorOut:
        return cls(id=d.id, department_id=d.department_id, display_name=d.display_name,
                   default_slot_minutes=d.default_slot_minutes, buffer_minutes=d.buffer_minutes, status=d.status,
                   current_delay_minutes=d.current_delay_minutes, is_active=d.is_active,
                   has_account=d.user_id is not None)


# ----------------------------------------------------------------- schedules
class ScheduleCreate(StrictModel):
    """A weekly recurring window in the clinic's local wall-clock time (no UTC offset)."""

    day_of_week: int = Field(ge=0, le=6, description="0 = Monday ... 6 = Sunday")
    start_time: time
    end_time: time
    valid_from: date | None = None
    valid_to: date | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def _wall_clock(cls, v: time) -> time:
        if v.tzinfo is not None:
            raise ValueError("Use clinic-local times without a timezone offset")
        return v.replace(microsecond=0)

    @model_validator(mode="after")
    def _ordering(self) -> ScheduleCreate:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return self


class ScheduleOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    day_of_week: int
    start_time: time
    end_time: time
    valid_from: date | None
    valid_to: date | None


# ------------------------------------------------------------------ time off
class TimeOffCreate(StrictModel):
    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> TimeOffCreate:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("starts_at and ends_at must include a timezone offset")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if (self.ends_at - self.starts_at).days > MAX_TIME_OFF_DAYS:
            raise ValueError(f"Time off cannot exceed {MAX_TIME_OFF_DAYS} days")
        return self

    def as_utc(self) -> tuple[datetime, datetime]:
        return self.starts_at.astimezone(UTC), self.ends_at.astimezone(UTC)


class TimeOffOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None
