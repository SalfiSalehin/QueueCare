from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import StrictModel


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown timezone") from None
    return value


class MemberOut(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    role: str
    is_active: bool


class MemberUpdate(StrictModel):
    is_active: bool


class ClinicSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    timezone: str
    created_at: datetime


class ClinicSettings(StrictModel):
    """Booking and queue rules. Stored as JSONB; always validated through this model."""

    booking_horizon_days: int = Field(default=60, ge=1, le=365)
    min_notice_minutes: int = Field(default=60, ge=0, le=1440)
    cancellation_cutoff_hours: int = Field(default=2, ge=0, le=168)
    queue_policy: Literal["APPOINTMENT_FIRST", "FIFO"] = "APPOINTMENT_FIRST"
    walkin_priority_enabled: bool = False


class ClinicDetail(ClinicSummary):
    settings: ClinicSettings


class ClinicUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    settings: ClinicSettings | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value is not None else None


def clinic_detail(c) -> ClinicDetail:  # noqa: ANN001 - ORM Clinic
    return ClinicDetail(id=c.id, name=c.name, slug=c.slug, status=c.status, timezone=c.timezone,
                        created_at=c.created_at, settings=ClinicSettings.model_validate(c.settings or {}))
