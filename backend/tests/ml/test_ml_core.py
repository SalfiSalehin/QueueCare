"""ML building blocks that need only the standard library: features, simulator, metrics.

These check correctness and leakage controls, not model quality. All data is synthetic.
"""
from __future__ import annotations

import math

import pytest

from ml.data_generation.simulator import generate
from ml.evaluation import metrics as M
from ml.preprocessing.features import (
    FEATURE_COLUMNS, MONOTONE_INCREASING, PRIOR_MEAN_SERVICE_MIN, TARGET, QueueSnapshot,
    features_from_snapshot, percentile,
)


def snap(**over) -> QueueSnapshot:
    base = dict(arrival_minute_of_day=600.0, day_of_week=1, is_scheduled=False, lateness_min=0.0, priority=0,
                n_scheduled_ahead=1, n_walkin_ahead=2, sched_slot_minutes_ahead=15.0, in_service=True,
                elapsed_in_service_min=5.0, doctor_recent_mean_service=10.0, doctor_recent_p80_service=14.0,
                slot_minutes=15.0, arrivals_last_30min=3)
    base.update(over)
    return QueueSnapshot(**base)


# ------------------------------------------------------------------- features
def test_feature_row_matches_the_declared_schema_exactly():
    row = features_from_snapshot(snap())
    assert tuple(row) == FEATURE_COLUMNS
    assert all(isinstance(v, float) and math.isfinite(v) for v in row.values())


def test_no_feature_is_named_after_something_that_happens_after_arrival():
    forbidden = {"wait", "start", "duration", "actual", "complete", "end", "target", "label"}
    for name in FEATURE_COLUMNS:                       # whole words only: "n_waiting_ahead" is fine
        assert not forbidden & set(name.split("_")), name
    assert TARGET not in FEATURE_COLUMNS
    assert MONOTONE_INCREASING <= set(FEATURE_COLUMNS)


def test_people_ahead_counts_the_consultation_in_progress():
    assert features_from_snapshot(snap(in_service=True))["people_ahead"] == 4.0
    assert features_from_snapshot(snap(in_service=False))["people_ahead"] == 3.0


def test_missing_history_uses_a_fixed_prior_and_says_so():
    row = features_from_snapshot(snap(doctor_recent_mean_service=None, doctor_recent_p80_service=None))
    assert row["has_history"] == 0.0 and row["doctor_recent_mean_service"] == PRIOR_MEAN_SERVICE_MIN
    assert features_from_snapshot(snap())["has_history"] == 1.0


def test_inputs_are_clipped_so_outliers_cannot_blow_up_the_model_input():
    row = features_from_snapshot(snap(elapsed_in_service_min=10_000, lateness_min=10_000))
    assert row["elapsed_in_service_min"] <= 180 and row["lateness_min"] <= 120
    assert features_from_snapshot(snap(in_service=False, elapsed_in_service_min=50))["elapsed_in_service_min"] == 0.0


def test_expected_work_ahead_grows_with_people_ahead():
    few = features_from_snapshot(snap(n_walkin_ahead=0))["expected_work_ahead_min"]
    many = features_from_snapshot(snap(n_walkin_ahead=6))["expected_work_ahead_min"]
    assert many > few


def test_percentile_matches_known_values():
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([10.0], 0.8) == 10.0
    assert percentile([0, 10], 0.25) == 2.5
    with pytest.raises(ValueError):
        percentile([], 0.5)


# ------------------------------------------------------------------- simulator
@pytest.fixture(scope="module")
def sample() -> list[dict]:
    return generate(seed=3, n_doctors=3, n_days=20)


def test_simulator_is_deterministic_and_seed_sensitive(sample):
    assert generate(seed=3, n_doctors=3, n_days=20) == sample
    assert generate(seed=4, n_doctors=3, n_days=20) != sample


def test_simulator_rows_are_synthetic_complete_and_sane(sample):
    assert len(sample) > 100
    for r in sample:
        assert r["is_synthetic"] is True
        assert set(FEATURE_COLUMNS) <= set(r) and TARGET in r
        assert r[TARGET] >= 0 and math.isfinite(r[TARGET])
        assert all(math.isfinite(float(r[c])) for c in FEATURE_COLUMNS)
        assert r["priority"] in (0, 1, 2)


def test_first_patient_of_the_day_with_nobody_ahead_waits_little(sample):
    empty = [r[TARGET] for r in sample if r["people_ahead"] == 0]
    assert empty, "expected some arrivals to an empty queue"
    assert sum(empty) / len(empty) < 10


def _pearson(a: list[float], b: list[float]) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def test_no_single_feature_leaks_the_target(sample):
    """A feature almost perfectly correlated with the label would suggest the label leaked in."""
    y = [float(r[TARGET]) for r in sample]
    for name in FEATURE_COLUMNS:
        corr = _pearson([float(r[name]) for r in sample], y)
        assert abs(corr) < 0.95, f"{name} correlates {corr:.3f} with the target"


# --------------------------------------------------------------------- metrics
def test_point_metrics_known_values():
    y, p = [10.0, 20.0, 30.0], [12.0, 18.0, 30.0]
    assert M.mae(y, p) == pytest.approx(4 / 3)
    assert M.rmse(y, p) == pytest.approx(math.sqrt(8 / 3))
    assert M.bias(y, p) == pytest.approx(0.0)
    assert M.share_within(y, p, 2) == pytest.approx(1.0)
    assert M.share_within(y, p, 1) == pytest.approx(1 / 3)


def test_metrics_reject_mismatched_or_empty_input():
    with pytest.raises(ValueError):
        M.mae([1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        M.mae([], [])


def test_pinball_loss_is_asymmetric():
    assert M.pinball([10.0], [8.0], 0.9) == pytest.approx(1.8)    # under-prediction costs alpha
    assert M.pinball([10.0], [12.0], 0.9) == pytest.approx(0.2)   # over-prediction costs 1-alpha


def test_coverage_and_width():
    assert M.coverage([5.0, 15.0], [0.0, 0.0], [10.0, 10.0]) == 0.5
    assert M.mean_width([0.0, 2.0], [10.0, 6.0]) == 7.0


def test_cqr_offset_reaches_target_coverage_on_its_calibration_data():
    y = [float(i) for i in range(100)]
    lower, upper = [v - 1 for v in y], [v + 1 for v in y]
    shifted_lo, shifted_hi = [v + 10 for v in lower], [v + 10 for v in upper]   # intervals miss: too high
    offset = M.cqr_offset(y, shifted_lo, shifted_hi, 0.8)
    lo, hi = M.apply_interval_offset(shifted_lo, shifted_hi, offset)
    assert M.coverage(y, lo, hi) >= 0.8
    assert all(a <= b for a, b in zip(lo, hi, strict=True)) and min(lo) >= 0


def test_default_dataset_meets_the_30k_row_requirement():
    assert len(generate()) >= 30_000
