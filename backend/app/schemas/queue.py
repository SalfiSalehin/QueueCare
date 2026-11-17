"""Request/response schemas for the live queue (Phase 5).

Patients get a deliberately small view (`MyTokenOut`): their own token and how many people are
ahead, never other patients' names.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import StrictModel


class WalkInCreate(StrictModel):
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    priority: int = Field(default=0, ge=0, le=2, description="0 normal, 1-2 urgent. Needs walkin_priority_enabled.")


class TransitionBody(StrictModel):
    reason: str | None = Field(default=None, max_length=200)


class TokenOut(BaseModel):
    id: uuid.UUID
    token_label: str
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    appointment_id: uuid.UUID | None
    source: str
    status: str
    priority: int
    queue_date: date
    arrived_at: datetime
    called_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    position: int | None = Field(default=None, description="1-based place among WAITING tokens; null otherwise")
    version: int


class QueueBoard(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    doctor_status: str
    queue_date: date
    policy: str
    serving: list[TokenOut]       # CALLED / IN_CONSULTATION (any date, so nothing is ever hidden)
    waiting: list[TokenOut]       # in the order they will be called
    skipped: list[TokenOut]
    finished_today: int


class MyTokenOut(BaseModel):
    id: uuid.UUID
    token_label: str
    doctor_id: uuid.UUID
    doctor_name: str
    status: str
    source: str
    queue_date: date
    people_ahead: int | None = Field(description="Patients to be seen before you; null if you are not waiting")


class TokenEventOut(BaseModel):
    from_status: str | None
    to_status: str
    reason: str | None
    actor_user_id: uuid.UUID | None
    created_at: datetime


class FactorOut(BaseModel):
    feature: str
    label: str
    minutes: float          # + pushed the estimate up, - pushed it down


class EstimateOut(BaseModel):
    """Estimated remaining wait for a waiting token. Staff and doctors also get the range."""

    token_id: uuid.UUID
    status: str
    source: str = Field(description="model | heuristic | not_waiting")
    median_minutes: float | None = None
    lower_minutes: float | None = Field(default=None, description="Staff/doctor view only")
    upper_minutes: float | None = Field(default=None, description="Staff/doctor view only")
    model_version: str | None = None
    factors: list[FactorOut] | None = Field(
        default=None, description="Staff/doctor view only: what moved the median estimate, in minutes")
    typical_minutes: float | None = Field(default=None, description="Staff/doctor view only: the model's baseline")
    note: str
