"""Appointment slot calculation. Pure functions: no database, no clock, no framework.

Rules
- A doctor's weekly windows are wall-clock times in the CLINIC's timezone. Each window is cut
  into a grid starting at the window start. One grid step = consultation + buffer.
- A slot OCCUPIES [start, start + consultation + buffer). The whole occupancy must fit inside
  the window, so buffers can never spill into an adjacent window and collide with it.
- The grid is laid out in real elapsed time (UTC), so a DST change inside a window shortens or
  lengthens the window honestly instead of producing impossible local times.
- A slot is bookable when it starts after `earliest` (now + minimum notice) and before `latest`
  (now + booking horizon), and its occupancy overlaps no busy interval (time off, other bookings).
- The database exclusion constraint on appointments remains the final authority against races.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Window:
    """A recurring weekly availability window. day_of_week: 0 = Monday ... 6 = Sunday."""

    day_of_week: int
    start_time: time
    end_time: time
    valid_from: date | None = None  # inclusive; None = open-ended
    valid_to: date | None = None

    def applies_on(self, day: date) -> bool:
        return (
            day.weekday() == self.day_of_week
            and (self.valid_from is None or day >= self.valid_from)
            and (self.valid_to is None or day <= self.valid_to)
        )


@dataclass(frozen=True)
class Slot:
    starts_at: datetime        # UTC
    ends_at: datetime          # UTC, end of the consultation itself
    occupies_until: datetime   # UTC, includes the buffer; stored as appointments.ends_at


def local_to_utc(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Clinic-local wall-clock time -> UTC. Times skipped by a DST jump resolve forward."""
    return datetime.combine(day, at.replace(tzinfo=None), tzinfo=tz).astimezone(UTC)


def day_bounds_utc(from_date: date, to_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start of from_date, start of the day after to_date) in UTC, using clinic-local midnights."""
    return (local_to_utc(from_date, time.min, tz),
            local_to_utc(to_date + timedelta(days=1), time.min, tz))


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def compute_slots(
    *,
    windows: Sequence[Window],
    tz: ZoneInfo,
    from_date: date,
    to_date: date,
    slot_minutes: int,
    buffer_minutes: int,
    busy: Sequence[tuple[datetime, datetime]],
    earliest: datetime,
    latest: datetime,
) -> list[Slot]:
    if to_date < from_date:
        raise ValueError("to_date must not be before from_date")
    if slot_minutes <= 0 or buffer_minutes < 0:
        raise ValueError("slot_minutes must be positive and buffer_minutes non-negative")

    consult = timedelta(minutes=slot_minutes)
    occupancy = timedelta(minutes=slot_minutes + buffer_minutes)
    slots: list[Slot] = []

    day = from_date
    while day <= to_date:
        for window in windows:
            if not window.applies_on(day):
                continue
            window_end = local_to_utc(day, window.end_time, tz)
            start = local_to_utc(day, window.start_time, tz)
            while start + occupancy <= window_end:
                end_occupied = start + occupancy
                if (
                    start >= earliest
                    and start < latest
                    and not any(_overlaps(start, end_occupied, b0, b1) for b0, b1 in busy)
                ):
                    slots.append(Slot(starts_at=start, ends_at=start + consult, occupies_until=end_occupied))
                start = end_occupied
        day += timedelta(days=1)

    slots.sort(key=lambda s: s.starts_at)
    return slots
