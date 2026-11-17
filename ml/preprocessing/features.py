"""Feature definitions shared by training AND serving (one code path, so no train/serve skew).

Everything here is computed from a `QueueSnapshot`: the state of a doctor's queue at the moment a
patient ARRIVES. Nothing in a snapshot may depend on what happens afterwards (leakage control):
no service start time, no waiting time, no duration of the patient's own consultation.

Pure standard library on purpose, so the data generator and the API can import it without pandas.
"""
from __future__ import annotations

from dataclasses import dataclass

# Fallbacks when a doctor has no completed consultations yet. They are fixed constants, not learned
# from the test set. `has_history` tells the model when they are in use.
PRIOR_MEAN_SERVICE_MIN = 12.0
PRIOR_P80_SERVICE_MIN = 18.0

FEATURE_COLUMNS: tuple[str, ...] = (
    "people_ahead",
    "n_waiting_ahead",
    "n_scheduled_ahead",
    "n_walkin_ahead",
    "in_service",
    "elapsed_in_service_min",
    "sched_slot_minutes_ahead",
    "doctor_recent_mean_service",
    "doctor_recent_p80_service",
    "has_history",
    "slot_minutes",
    "expected_work_ahead_min",
    "arrivals_last_30min",
    "hour_of_day",
    "day_of_week",
    "is_scheduled",
    "lateness_min",
    "priority",
)

# Plain-language names used when explaining a prediction to staff.
FEATURE_LABELS: dict[str, str] = {
    "people_ahead": "People ahead in the queue",
    "n_waiting_ahead": "Patients waiting ahead",
    "n_scheduled_ahead": "Booked patients ahead",
    "n_walkin_ahead": "Walk-ins ahead",
    "in_service": "A consultation is in progress",
    "elapsed_in_service_min": "Time the current consultation has already run",
    "sched_slot_minutes_ahead": "Booked time ahead",
    "doctor_recent_mean_service": "Doctor's recent average consultation length",
    "doctor_recent_p80_service": "Doctor's recent longer consultations",
    "has_history": "Doctor has recent history",
    "slot_minutes": "Configured slot length",
    "expected_work_ahead_min": "Expected work ahead",
    "arrivals_last_30min": "Recent arrivals (last 30 min)",
    "hour_of_day": "Time of day",
    "day_of_week": "Day of the week",
    "is_scheduled": "Booked appointment (vs walk-in)",
    "lateness_min": "Lateness for the appointment",
    "priority": "Urgency",
}

# More people / more planned work ahead can never SHORTEN the wait. Enforced as monotone
# constraints in the L2 LightGBM model (LightGBM disallows them for the quantile objective).
MONOTONE_INCREASING: frozenset[str] = frozenset(
    {"people_ahead", "n_waiting_ahead", "n_scheduled_ahead", "n_walkin_ahead",
     "sched_slot_minutes_ahead", "expected_work_ahead_min"}
)

TARGET = "wait_minutes"           # minutes from arrival until the consultation starts


@dataclass(frozen=True)
class QueueSnapshot:
    arrival_minute_of_day: float          # clinic-local minutes since midnight
    day_of_week: int                      # 0 = Monday
    is_scheduled: bool                    # booked appointment (True) or walk-in (False)
    lateness_min: float                   # arrival minus appointment start; 0 for walk-ins
    priority: int                         # 0 normal, 1-2 urgent
    n_scheduled_ahead: int                # waiting patients who will be seen before this one: booked
    n_walkin_ahead: int                   # ... walk-ins
    sched_slot_minutes_ahead: float       # sum of planned slot lengths of the booked patients ahead
    in_service: bool                      # a consultation is currently being held
    elapsed_in_service_min: float         # how long the current consultation has run (0 if none)
    doctor_recent_mean_service: float | None   # mean of the doctor's last completed consultations
    doctor_recent_p80_service: float | None
    slot_minutes: float                   # the doctor's configured slot length
    arrivals_last_30min: int              # arrivals to this doctor's queue in the previous 30 minutes


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def features_from_snapshot(s: QueueSnapshot) -> dict[str, float]:
    """The model input row. Keys are exactly FEATURE_COLUMNS, in that order."""
    has_history = s.doctor_recent_mean_service is not None
    mean = s.doctor_recent_mean_service if has_history else PRIOR_MEAN_SERVICE_MIN
    p80 = s.doctor_recent_p80_service if s.doctor_recent_p80_service is not None else PRIOR_P80_SERVICE_MIN
    n_ahead = s.n_scheduled_ahead + s.n_walkin_ahead
    elapsed = _clip(s.elapsed_in_service_min, 0.0, 180.0) if s.in_service else 0.0
    remaining_current = max(0.0, mean - elapsed) if s.in_service else 0.0
    row = {
        "people_ahead": float(n_ahead + (1 if s.in_service else 0)),
        "n_waiting_ahead": float(n_ahead),
        "n_scheduled_ahead": float(s.n_scheduled_ahead),
        "n_walkin_ahead": float(s.n_walkin_ahead),
        "in_service": 1.0 if s.in_service else 0.0,
        "elapsed_in_service_min": float(elapsed),
        "sched_slot_minutes_ahead": float(s.sched_slot_minutes_ahead),
        "doctor_recent_mean_service": float(mean),
        "doctor_recent_p80_service": float(p80),
        "has_history": 1.0 if has_history else 0.0,
        "slot_minutes": float(s.slot_minutes),
        "expected_work_ahead_min": float(n_ahead * mean + remaining_current),
        "arrivals_last_30min": float(s.arrivals_last_30min),
        "hour_of_day": float(s.arrival_minute_of_day) / 60.0,
        "day_of_week": float(s.day_of_week),
        "is_scheduled": 1.0 if s.is_scheduled else 0.0,
        "lateness_min": float(_clip(s.lateness_min, -60.0, 120.0)),
        "priority": float(s.priority),
    }
    assert tuple(row) == FEATURE_COLUMNS
    return row


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (same convention as numpy's default). Stdlib only."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty")
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)
