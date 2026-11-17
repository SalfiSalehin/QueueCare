"""Slot-length suggestions from observed consultation lengths (pure; no database).

This is plain statistics, not machine learning, so it can be explained in one sentence: choose the
shortest slot (a multiple of 5 minutes) that at least 80% of this doctor's recent consultations fit
into. The suggestion is advice for a human; nothing is changed automatically.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

MIN_SAMPLES = 30            # fewer completed consultations than this: no suggestion
FIT_SHARE = 0.80            # the suggested slot should fit this share of consultations
STEP = 5
MIN_SLOT, MAX_SLOT = 10, 60
SHORTEN_BY_AT_LEAST = 10    # slots only slightly longer than needed are left alone


@dataclass(frozen=True)
class Suggestion:
    status: str                      # insufficient_data | keep | lengthen | shorten
    n: int
    current_slot_minutes: int
    suggested_slot_minutes: int | None
    median_minutes: float | None
    p80_minutes: float | None
    overrun_share_now: float | None          # consultations longer than the current slot
    overrun_share_suggested: float | None    # ... longer than the suggested slot


def quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (same convention as the analytics endpoints)."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _overrun(durations: Sequence[float], slot: float) -> float:
    return round(sum(1 for d in durations if d > slot) / len(durations), 4)


def suggest(durations: Sequence[float], current_slot: int) -> Suggestion:
    n = len(durations)
    if n < MIN_SAMPLES:
        return Suggestion("insufficient_data", n, current_slot, None, None, None, None, None)
    p80 = quantile(durations, FIT_SHARE)
    suggested = int(min(MAX_SLOT, max(MIN_SLOT, math.ceil(p80 / STEP) * STEP)))
    if suggested > current_slot:
        status = "lengthen"
    elif current_slot - suggested >= SHORTEN_BY_AT_LEAST:
        status = "shorten"
    else:
        status = "keep"
    return Suggestion(
        status=status, n=n, current_slot_minutes=current_slot, suggested_slot_minutes=suggested,
        median_minutes=round(quantile(durations, 0.5), 1), p80_minutes=round(p80, 1),
        overrun_share_now=_overrun(durations, current_slot), overrun_share_suggested=_overrun(durations, suggested))
