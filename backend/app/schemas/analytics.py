from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel


class DateRange(BaseModel):
    start: date
    end: date                       # inclusive, clinic-local dates
    timezone: str


class Distribution(BaseModel):
    n: int
    mean: float | None = None
    p50: float | None = None
    p90: float | None = None
    max: float | None = None


class DayPoint(BaseModel):
    date: date
    appointments: int
    arrivals: int
    consultations: int


class OverviewOut(BaseModel):
    range: DateRange
    appointments_total: int
    appointments_by_status: dict[str, int]
    no_show_rate: float | None          # NO_SHOW / (COMPLETED + NO_SHOW)
    cancellation_rate: float | None     # CANCELLED / all appointments
    tokens_total: int
    tokens_by_status: dict[str, int]
    walk_in_share: float | None
    wait_minutes: Distribution          # arrival -> consultation start
    consultation_minutes: Distribution
    daily: list[DayPoint]


class DoctorUtilisation(BaseModel):
    doctor_id: uuid.UUID
    display_name: str
    scheduled_minutes: float
    booked_minutes: float               # non-cancelled appointments incl. their buffers
    consultation_minutes: float         # time actually spent in consultations
    patients_seen: int
    avg_wait_minutes: float | None
    booked_utilisation: float | None    # booked / scheduled
    busy_utilisation: float | None      # consultation / scheduled


class DoctorUtilisationOut(BaseModel):
    range: DateRange
    items: list[DoctorUtilisation]


class HourLoad(BaseModel):
    hour: int
    arrivals: int
    avg_wait_minutes: float | None


class WeekdayLoad(BaseModel):
    weekday: int                        # 0 = Monday
    arrivals: int


class LoadOut(BaseModel):
    range: DateRange
    by_hour: list[HourLoad]
    by_weekday: list[WeekdayLoad]


class VersionAccuracy(BaseModel):
    model_version: str
    n: int
    mae_minutes: float | None
    median_abs_error_minutes: float | None
    bias_minutes: float | None          # mean(predicted - actual); negative = under-predicts
    interval_coverage: float | None     # share of actual waits inside [lower, upper]
    naive_baseline_mae_minutes: float | None   # "people ahead x recent mean", from the same rows


class PredictionAccuracyOut(BaseModel):
    range: DateRange
    versions: list[VersionAccuracy]
    enough_data: bool                   # False below 30 completed predictions: do not read much into it
    note: str


# ------------------------------------------------------------------ drift (Phase 9)
class FeatureDrift(BaseModel):
    feature: str
    label: str
    psi: float
    status: str                         # stable | moderate | high


class PerformanceDrift(BaseModel):
    n: int
    recent_mae_minutes: float | None
    reference_mae_minutes: float | None   # measured on held-out synthetic test data at training time
    status: str                           # ok | watch | degraded | insufficient_data | unknown


class DriftOut(BaseModel):
    status: str                           # ok | no_model | no_reference | insufficient_data
    model_version: str | None
    window_days: int
    samples: int                          # live predictions compared
    overall: str | None                   # worst feature status, when computed
    features: list[FeatureDrift]
    performance: PerformanceDrift | None
    note: str


# --------------------------------------------------------- scheduling suggestions
class SlotSuggestion(BaseModel):
    doctor_id: uuid.UUID
    display_name: str
    status: str                           # insufficient_data | keep | lengthen | shorten
    consultations: int
    current_slot_minutes: int
    suggested_slot_minutes: int | None
    median_minutes: float | None
    p80_minutes: float | None
    overrun_share_now: float | None
    overrun_share_suggested: float | None
    advice: str


class SchedulingSuggestionsOut(BaseModel):
    window_days: int
    items: list[SlotSuggestion]
    note: str
