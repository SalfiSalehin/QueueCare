"""Slot-length suggestion rules (pure statistics, no database)."""
from __future__ import annotations

import pytest

from app.services.scheduling_logic import MIN_SAMPLES, quantile, suggest


def test_quantile_interpolates_and_rejects_empty():
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([5], 0.8) == 5
    assert quantile([10, 20], 0.0) == 10 and quantile([10, 20], 1.0) == 20
    with pytest.raises(ValueError):
        quantile([], 0.5)


def test_too_few_samples_gives_no_suggestion():
    s = suggest([10.0] * (MIN_SAMPLES - 1), 15)
    assert s.status == "insufficient_data" and s.suggested_slot_minutes is None and s.n == MIN_SAMPLES - 1


def test_lengthen_when_consultations_overrun_the_slot():
    s = suggest([22.0] * 40, 15)
    assert s.status == "lengthen" and s.suggested_slot_minutes == 25
    assert s.overrun_share_now == 1.0 and s.overrun_share_suggested == 0.0


def test_shorten_only_when_clearly_too_long():
    assert suggest([10.0] * 40, 30).status == "shorten"
    assert suggest([10.0] * 40, 30).suggested_slot_minutes == 10
    assert suggest([12.0] * 40, 20).status == "keep"   # 15 vs 20: only 5 minutes of slack


def test_suggestion_is_a_multiple_of_five_and_clamped():
    assert suggest([1.0] * 40, 15).suggested_slot_minutes == 10
    assert suggest([200.0] * 40, 15).suggested_slot_minutes == 60
    assert suggest([13.3] * 40, 15).suggested_slot_minutes % 5 == 0


def test_suggested_slot_fits_at_least_eighty_percent():
    durations = [float(5 + (i % 20)) for i in range(100)]
    s = suggest(durations, 15)
    fit = sum(1 for d in durations if d <= s.suggested_slot_minutes) / len(durations)
    assert fit >= 0.8
