"""Pure analytics helpers (no database): working time and simple ratios."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ScheduleRule:
    day_of_week: int          # 0 = Monday
    start_time: time
    end_time: time
    valid_from: date | None = None
    valid_to: date | None = None


Interval = tuple[datetime, datetime]


def _merge(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _overlap_minutes(window: Interval, others: list[Interval]) -> float:
    total = 0.0
    for start, end in _merge(others):
        lo, hi = max(window[0], start), min(window[1], end)
        if hi > lo:
            total += (hi - lo).total_seconds() / 60.0
    return total


def scheduled_minutes(rules: list[ScheduleRule], time_off: list[Interval], first: date, last: date,
                      tz: ZoneInfo) -> float:
    """Minutes a doctor was scheduled to work between two clinic-local dates (inclusive), minus time off.

    Overlapping rules on the same day are merged, so the same minute is never counted twice."""
    total = 0.0
    day = first
    while day <= last:
        windows: list[Interval] = []
        for rule in rules:
            if rule.day_of_week != day.weekday():
                continue
            if rule.valid_from is not None and day < rule.valid_from:
                continue
            if rule.valid_to is not None and day > rule.valid_to:
                continue
            start = datetime.combine(day, rule.start_time, tzinfo=tz).astimezone(UTC)
            end = datetime.combine(day, rule.end_time, tzinfo=tz).astimezone(UTC)
            windows.append((start, end))
        for window in _merge(windows):
            total += (window[1] - window[0]).total_seconds() / 60.0 - _overlap_minutes(window, time_off)
        day += timedelta(days=1)
    return max(0.0, total)


def ratio(numerator: float, denominator: float) -> float | None:
    """numerator / denominator, or None when the denominator is zero (no data, not "0%")."""
    return None if not denominator else round(numerator / denominator, 4)
