"""Simulation lab: "what if?" runs on the SYNTHETIC queue simulator (pure standard library, deterministic).

It answers questions such as "what happens to waits if walk-ins double, consultations run 20% longer, or
slots go from 15 to 20 minutes?". It is NOT a forecast of a real clinic:

* the simulator's behaviour comes from rules written in `ml/data_generation/simulator.py`, with only the
  parameters below changed (it knows nothing about the clinic's real patients);
* every simulated doctor has their own queue and their own patients, so adding doctors does NOT spread
  demand. The `doctors` setting only sets the sample size. It cannot model "hire one more doctor".

Same scenario + same seed always gives the same numbers.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from ml.data_generation.simulator import (
    DAY_END_MIN, DAY_START_MIN, DoctorProfile, _DoctorState, simulate_doctor_day, working_days,
)
from ml.preprocessing.features import percentile

WORKDAY_MINUTES = DAY_END_MIN - DAY_START_MIN

LIMITS: dict[str, tuple[float, float]] = {
    "doctors": (1, 6), "days": (5, 30), "mean_service_minutes": (5, 40), "slot_minutes": (5, 60),
    "booked_share": (0.0, 1.0), "walk_in_per_hour": (0.0, 4.0),
}


@dataclass(frozen=True)
class Scenario:
    name: str = "Scenario"
    doctors: int = 3                       # sample size only (see module docstring)
    days: int = 20
    mean_service_minutes: float = 12.0     # nominal consultation length
    slot_minutes: int = 15
    booked_share: float = 0.65             # share of appointment slots that get booked
    walk_in_per_hour: float = 1.0          # base walk-in arrivals per doctor-hour
    seed: int = 1


@dataclass(frozen=True)
class Outcome:
    visits: int
    mean_wait_minutes: float
    median_wait_minutes: float
    p90_wait_minutes: float
    share_waiting_over_30_min: float
    mean_consultation_minutes: float
    utilisation: float                     # consultation time / working time (09:00-17:00)
    overtime_day_share: float              # share of doctor-days finishing after 17:00
    mean_overtime_minutes: float           # on those days


def validate(s: Scenario) -> None:
    for field, (low, high) in LIMITS.items():
        value = getattr(s, field)
        if not low <= value <= high:
            raise ValueError(f"{field} must be between {low} and {high}")


def run(s: Scenario) -> Outcome:
    validate(s)
    profiles = [DoctorProfile(doctor_id=i, mean_service_min=s.mean_service_minutes, slot_minutes=s.slot_minutes,
                              book_rate=s.booked_share, walkin_per_hour=s.walk_in_per_hour, followup_share=0.45)
                for i in range(s.doctors)]
    states = {p.doctor_id: _DoctorState() for p in profiles}
    waits: list[float] = []
    service_total = 0.0
    overtime: list[float] = []
    doctor_days = 0
    for day_index, weekday in working_days(s.days):
        for doc in profiles:
            rng = random.Random(f"queuecare-lab-{s.seed}-{doc.doctor_id}-{day_index}")  # noqa: S311 - simulation
            seen = simulate_doctor_day(rng, doc, states[doc.doctor_id], weekday)
            doctor_days += 1
            finish = 0.0
            for p in seen:
                waits.append(p.wait)
                service_total += p.service
                finish = max(finish, (p.start or 0.0) + p.service)
            if finish > DAY_END_MIN:
                overtime.append(finish - DAY_END_MIN)
    if not waits:
        return Outcome(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    n = len(waits)
    return Outcome(
        visits=n, mean_wait_minutes=round(sum(waits) / n, 2), median_wait_minutes=round(percentile(waits, 0.5), 2),
        p90_wait_minutes=round(percentile(waits, 0.9), 2),
        share_waiting_over_30_min=round(sum(1 for w in waits if w > 30) / n, 4),
        mean_consultation_minutes=round(service_total / n, 2),
        utilisation=round(service_total / (doctor_days * WORKDAY_MINUTES), 4),
        overtime_day_share=round(len(overtime) / doctor_days, 4),
        mean_overtime_minutes=round(sum(overtime) / len(overtime), 1) if overtime else 0.0)


def outcome_dict(o: Outcome) -> dict[str, float | int]:
    return asdict(o)
