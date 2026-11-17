"""Request/response schemas for slots, appointments and clinic patients (Phase 4).

Clients never choose appointment duration or end time: the server derives them from the
doctor's configuration, so a request cannot book more time than the schedule allows.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.permissions.roles import AppointmentStatus
from app.schemas.common import StrictModel

PHONE_RE = re.compile(r"^[0-9+()\- ]{6,32}$")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamps must include a timezone offset, e.g. 2030-01-07T09:00:00+06:00")
    return value.astimezone(UTC)


# ---------------------------------------------------------------------- slots
class SlotOut(BaseModel):
    starts_at: datetime
    ends_at: datetime          # end of the consultation (the buffer after it is not shown)
    starts_at_local: str       # ISO time in the clinic's timezone, for display


class DoctorAvailability(BaseModel):
    doctor_id: uuid.UUID
    display_name: str
    department_id: uuid.UUID
    same_department: bool
    earliest: SlotOut | None      # first bookable slot in the range, None if there is none
    slots_in_range: int


class AlternativesOut(BaseModel):
    """When the requested doctor is fully booked, who else could see the patient soonest."""

    requested: DoctorAvailability
    alternatives: list[DoctorAvailability]     # only doctors that DO have a slot, earliest first


# --------------------------------------------------------------- appointments
class AppointmentCreate(StrictModel):
    doctor_id: uuid.UUID
    starts_at: datetime
    patient_id: uuid.UUID | None = Field(
        default=None, description="Staff only: the clinic patient to book for. Patients must omit it.")

    @field_validator("starts_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return _aware_utc(v)


class AppointmentReschedule(StrictModel):
    starts_at: datetime
    doctor_id: uuid.UUID | None = Field(default=None, description="Omit to keep the same doctor")

    @field_validator("starts_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return _aware_utc(v)


class AppointmentCancel(StrictModel):
    reason: str | None = Field(default=None, max_length=200)


class AppointmentOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    doctor_name: str
    patient_id: uuid.UUID
    patient_name: str
    starts_at: datetime
    ends_at: datetime          # occupied range end: INCLUDES the doctor's buffer
    starts_at_local: str
    status: str
    rescheduled_from: uuid.UUID | None
    cancel_reason: str | None

    @classmethod
    def build(cls, appt: Any, doctor_name: str, patient_name: str, tz: Any) -> AppointmentOut:
        return cls(
            id=appt.id, doctor_id=appt.doctor_id, doctor_name=doctor_name, patient_id=appt.patient_id,
            patient_name=patient_name, starts_at=appt.starts_at.astimezone(UTC), ends_at=appt.ends_at.astimezone(UTC),
            starts_at_local=appt.starts_at.astimezone(tz).isoformat(), status=appt.status,
            rescheduled_from=appt.rescheduled_from, cancel_reason=appt.cancel_reason,
        )


class AppointmentFilters(BaseModel):
    """Documented shape of the list query parameters (declared individually on the route)."""

    doctor_id: uuid.UUID | None = None
    status: AppointmentStatus | None = None
    on_date: date | None = None


# ------------------------------------------------------------------- patients
class PatientCreate(StrictModel):
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is not None and not PHONE_RE.match(v):
            raise ValueError("Phone may contain digits, spaces and + ( ) - only")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: date | None) -> date | None:
        if v is not None and not (date(1900, 1, 1) <= v <= datetime.now(UTC).date()):
            raise ValueError("date_of_birth is out of range")
        return v


class PatientOut(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str | None
    date_of_birth: date | None
    has_account: bool
