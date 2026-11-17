from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import StrictModel


class ScenarioIn(StrictModel):
    name: str = Field(default="Scenario", min_length=1, max_length=60)
    doctors: int = Field(default=3, ge=1, le=6, description="Sample size only: each doctor has their own queue")
    days: int = Field(default=20, ge=5, le=30)
    mean_service_minutes: float = Field(default=12.0, ge=5, le=40)
    slot_minutes: int = Field(default=15, ge=5, le=60)
    booked_share: float = Field(default=0.65, ge=0, le=1)
    walk_in_per_hour: float = Field(default=1.0, ge=0, le=4)
    seed: int = Field(default=1, ge=0, le=1_000_000)


class SimulationIn(StrictModel):
    scenarios: list[ScenarioIn] = Field(min_length=1, max_length=3)


class OutcomeOut(BaseModel):
    visits: int
    mean_wait_minutes: float
    median_wait_minutes: float
    p90_wait_minutes: float
    share_waiting_over_30_min: float
    mean_consultation_minutes: float
    utilisation: float
    overtime_day_share: float
    mean_overtime_minutes: float


class ScenarioResult(BaseModel):
    scenario: ScenarioIn
    outcome: OutcomeOut
    mean_wait_change_minutes: float | None      # vs the first scenario (None for the first)
    p90_wait_change_minutes: float | None
    utilisation_change: float | None


class SimulationOut(BaseModel):
    synthetic: bool = True
    results: list[ScenarioResult]
    note: str
