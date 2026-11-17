"""Synthetic clinic-queue simulator. ALL OUTPUT IS SYNTHETIC; there is no real patient data anywhere.

A discrete-event simulation of single-doctor queues over many working days:

* Booked patients arrive around their slot time (usually a few minutes early or late) and a few
  never show up.
* Walk-ins arrive as a non-homogeneous Poisson process (busier mid-morning and mid-afternoon,
  busiest on Mondays).
* Service time is log-normal around a per-doctor mean, shorter for follow-ups, longer in the late
  afternoon, with occasional long complex cases.
* Occasional unobserved interruptions (e.g. an urgent phone call) delay a consultation. They are
  part of the noise a model cannot predict.
* Queue discipline matches the product default (APPOINTMENT_FIRST): urgent first, then booked
  patients by appointment time, then walk-ins by arrival.

Because the rules are written down here, a model can only learn what this generator contains. The
results say nothing about real clinics, and the README says so.

The generator records, for each visit, the queue state at ARRIVAL (a QueueSnapshot, converted to
features by the same function the API uses) and the observed waiting time as the label.
Pure standard library: deterministic for a given seed.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from ml.preprocessing.features import QueueSnapshot, features_from_snapshot, percentile

GENERATOR_VERSION = "1.0"
DAY_START_MIN = 9 * 60
DAY_END_MIN = 17 * 60                 # last scheduled slot ends here
WALKIN_CUTOFF_MIN = 16 * 60 + 30      # no walk-ins after this
WALKIN_QUEUE_LIMIT = 12               # front desk stops taking walk-ins when this many are waiting
HISTORY_LEN = 10                      # consultations used for the doctor's recent mean
WEEKDAY_LOAD = {0: 1.30, 1: 1.10, 2: 1.00, 3: 1.00, 4: 0.95, 5: 0.70}   # Mon..Sat (Sunday closed)
# Relative walk-in intensity by clock hour (peaks mid-morning and mid-afternoon)
HOUR_LOAD = {9: 0.8, 10: 1.4, 11: 1.5, 12: 0.8, 13: 0.7, 14: 1.1, 15: 1.4, 16: 0.9}
DEPARTMENT_COMPLEXITY = (0.85, 1.00, 1.20, 1.40)   # e.g. general, paediatrics, cardiology, orthopaedics


@dataclass(frozen=True)
class DoctorProfile:
    doctor_id: int
    mean_service_min: float        # typical consultation length
    slot_minutes: int              # configured booking slot
    book_rate: float               # share of slots that are booked
    walkin_per_hour: float         # base walk-in arrivals per hour
    followup_share: float


@dataclass
class _Patient:
    arrival: float
    scheduled: bool
    appt_start: float
    slot_min: float
    priority: int
    followup: bool
    snapshot: QueueSnapshot | None = None
    start: float | None = None
    service: float = 0.0
    wait: float = 0.0


@dataclass
class _DoctorState:
    recent: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))


def make_doctors(rng: random.Random, n: int) -> list[DoctorProfile]:
    doctors = []
    for i in range(n):
        complexity = DEPARTMENT_COMPLEXITY[i % len(DEPARTMENT_COMPLEXITY)]
        mean = max(6.0, rng.uniform(8.0, 14.0) * complexity)
        slot = int(min(30, max(10, 5 * round(mean * 1.3 / 5))))
        doctors.append(DoctorProfile(
            doctor_id=i, mean_service_min=mean, slot_minutes=slot,
            book_rate=rng.uniform(0.52, 0.78), walkin_per_hour=rng.uniform(0.5, 1.4),
            followup_share=rng.uniform(0.3, 0.6),
        ))
    return doctors


def _service_minutes(rng: random.Random, doc: DoctorProfile, p: _Patient, start: float) -> float:
    mean = doc.mean_service_min * (0.75 if p.followup else 1.2)
    if start >= 14 * 60:
        mean *= 1.08                                   # late-day fatigue
    sigma = 0.35
    value = mean * math.exp(rng.gauss(-sigma * sigma / 2, sigma))   # E[value] == mean
    if rng.random() < 0.04:
        value *= rng.uniform(2.0, 3.0)                 # occasional complex case
    return max(3.0, value)


def _arrivals(rng: random.Random, doc: DoctorProfile, weekday: int) -> list[_Patient]:
    out: list[_Patient] = []
    t = DAY_START_MIN
    while t + doc.slot_minutes <= DAY_END_MIN:        # booked patients
        if rng.random() < doc.book_rate and rng.random() >= 0.08:      # 8% no-shows
            lateness = min(45.0, max(-20.0, rng.gauss(-3.0, 7.0)))
            out.append(_Patient(arrival=t + lateness, scheduled=True, appt_start=float(t),
                                slot_min=float(doc.slot_minutes),
                                priority=1 if rng.random() < 0.02 else 0,
                                followup=rng.random() < doc.followup_share))
        t += doc.slot_minutes
    peak = WEEKDAY_LOAD[weekday] * doc.walkin_per_hour * max(HOUR_LOAD.values())
    if peak <= 0:                                     # no walk-ins at all (used by the simulation lab)
        out.sort(key=lambda p: p.arrival)
        return out
    t = float(DAY_START_MIN)                          # walk-ins: thinning of a Poisson process
    while True:
        t += rng.expovariate(peak / 60.0)
        if t >= WALKIN_CUTOFF_MIN:
            break
        rate = WEEKDAY_LOAD[weekday] * doc.walkin_per_hour * HOUR_LOAD[int(t // 60)]
        if rng.random() < rate / peak:
            out.append(_Patient(arrival=t, scheduled=False, appt_start=t, slot_min=0.0,
                                priority=2 if rng.random() < 0.03 else 0,
                                followup=rng.random() < doc.followup_share))
    out.sort(key=lambda p: p.arrival)
    return out


def _order_key(p: _Patient) -> tuple[int, int, float]:
    # urgent first, then booked (by appointment time), then walk-ins (by arrival)
    return (-p.priority, 0 if p.scheduled else 1, p.appt_start if p.scheduled else p.arrival)


def simulate_doctor_day(rng: random.Random, doc: DoctorProfile, state: _DoctorState,
                        weekday: int) -> list[_Patient]:
    arrivals = _arrivals(rng, doc, weekday)
    interruption_at = (rng.uniform(DAY_START_MIN + 60, DAY_END_MIN - 60) if rng.random() < 0.05 else None)
    interruption_len = rng.uniform(15.0, 40.0)
    waiting: list[_Patient] = []
    in_service: tuple[_Patient, float] | None = None       # (patient, end time)
    seen: list[_Patient] = []
    recent_arrivals: deque[float] = deque()
    i = 0

    def start_next(now: float) -> None:
        nonlocal in_service, interruption_at
        waiting.sort(key=_order_key)
        p = waiting.pop(0)
        p.start = now
        p.wait = now - p.arrival
        p.service = _service_minutes(rng, doc, p, now)
        if interruption_at is not None and now <= interruption_at < now + p.service:
            p.service += interruption_len                  # unobservable delay
            interruption_at = None
        in_service = (p, now + p.service)

    while i < len(arrivals) or waiting or in_service is not None:
        next_arrival = arrivals[i].arrival if i < len(arrivals) else math.inf
        if in_service is not None and in_service[1] <= next_arrival:
            done, end = in_service
            in_service = None
            seen.append(done)
            state.recent.append(done.service)
            if waiting:
                start_next(end)
            continue
        p = arrivals[i]
        i += 1
        now = p.arrival
        if not p.scheduled and len(waiting) >= WALKIN_QUEUE_LIMIT:
            continue                                       # turned away: never joins the queue
        key = _order_key(p)
        ahead = [w for w in waiting if _order_key(w) < key]
        recent = list(state.recent)
        while recent_arrivals and recent_arrivals[0] < now - 30.0:
            recent_arrivals.popleft()
        p.snapshot = QueueSnapshot(
            arrival_minute_of_day=now, day_of_week=weekday, is_scheduled=p.scheduled,
            lateness_min=(now - p.appt_start) if p.scheduled else 0.0, priority=p.priority,
            n_scheduled_ahead=sum(1 for w in ahead if w.scheduled),
            n_walkin_ahead=sum(1 for w in ahead if not w.scheduled),
            sched_slot_minutes_ahead=sum(w.slot_min for w in ahead if w.scheduled),
            in_service=in_service is not None,
            elapsed_in_service_min=(now - (in_service[1] - in_service[0].service)) if in_service else 0.0,
            doctor_recent_mean_service=(sum(recent) / len(recent)) if recent else None,
            doctor_recent_p80_service=percentile(recent, 0.8) if recent else None,
            slot_minutes=float(doc.slot_minutes), arrivals_last_30min=len(recent_arrivals),
        )
        recent_arrivals.append(now)
        waiting.append(p)
        if in_service is None:
            start_next(now)                                # idle doctor: seen straight away
    return seen


def working_days(n_days: int) -> list[tuple[int, int]]:
    """(day_index, weekday) for n_days consecutive working days, skipping Sundays. Day 0 is a Monday."""
    out, day = [], 0
    while len(out) < n_days:
        weekday = day % 7
        if weekday != 6:
            out.append((len(out), weekday))
        day += 1
    return out


def generate(seed: int = 42, n_doctors: int = 12, n_days: int = 200) -> list[dict[str, float | int | bool]]:
    """Return one dict per visit: identifiers, the feature columns, the label, and `is_synthetic`."""
    setup_rng = random.Random(f"queuecare-setup-{seed}")  # noqa: S311 - simulation, not security
    doctors = make_doctors(setup_rng, n_doctors)
    states = {d.doctor_id: _DoctorState() for d in doctors}
    rows: list[dict[str, float | int | bool]] = []
    for day_index, weekday in working_days(n_days):
        for doc in doctors:
            rng = random.Random(f"queuecare-{seed}-{doc.doctor_id}-{day_index}")  # noqa: S311 - simulation
            for p in simulate_doctor_day(rng, doc, states[doc.doctor_id], weekday):
                assert p.snapshot is not None
                row: dict[str, float | int | bool] = {
                    "day_index": day_index, "doctor_id": doc.doctor_id,
                    **features_from_snapshot(p.snapshot),
                    "wait_minutes": round(p.wait, 4),
                    "is_synthetic": True,
                }
                rows.append(row)
    return rows
