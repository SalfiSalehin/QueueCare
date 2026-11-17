"""Pure (no LightGBM, no database) tests for drift statistics, the reference builder and the simulation lab."""
from __future__ import annotations

import random  # noqa: S311 - synthetic test data

import pytest

from ml.monitoring import drift
from ml.monitoring.reference import build_reference
from ml.preprocessing.features import FEATURE_COLUMNS
from ml.simulation.lab import Scenario, run, validate


# ----------------------------------------------------------------------------- drift
def test_few_distinct_values_are_binned_by_value_and_sum_to_one():
    spec = drift.build_feature_reference([0, 1, 1, 2, 2, 2, 3, 3, 3, 3])
    assert spec["kind"] == "values" and spec["points"] == [0, 1, 2, 3]
    assert sum(spec["proportions"]) == pytest.approx(1.0, abs=1e-4)
    assert len(spec["proportions"]) == len(spec["points"]) + 1  # plus the "unseen value" bin


def test_many_distinct_values_use_quantile_edges():
    rng = random.Random(1)  # noqa: S311
    spec = drift.build_feature_reference([rng.random() for _ in range(1000)])
    assert spec["kind"] == "edges" and len(spec["points"]) <= drift.N_QUANTILE_BINS - 1
    assert all(0.05 < p < 0.2 for p in spec["proportions"])


def test_empty_reference_is_rejected():
    with pytest.raises(ValueError):
        drift.build_feature_reference([])


def test_unseen_category_goes_to_its_own_bin():
    spec = drift.build_feature_reference([0, 1, 2])
    assert drift.bin_counts(spec, [9, 9, 0]) == [1, 0, 0, 2]


def test_psi_is_zero_for_identical_and_large_for_shifted():
    rng = random.Random(2)  # noqa: S311
    train = [rng.gauss(0, 1) for _ in range(5000)]
    spec = drift.build_feature_reference(train)
    same = [rng.gauss(0, 1) for _ in range(2000)]
    shifted = [rng.gauss(3, 1) for _ in range(2000)]
    assert drift.psi(spec["proportions"], drift.bin_counts(spec, same)) < drift.STABLE_PSI
    assert drift.psi(spec["proportions"], drift.bin_counts(spec, shifted)) > drift.HIGH_PSI
    assert drift.psi([0.5, 0.5], [10, 10]) == pytest.approx(0.0, abs=1e-9)


def test_psi_validates_inputs_and_survives_empty_bins():
    with pytest.raises(ValueError):
        drift.psi([0.5, 0.5], [1])
    with pytest.raises(ValueError):
        drift.psi([0.5, 0.5], [0, 0])
    assert drift.psi([0.5, 0.5], [10, 0]) > 0  # finite, no log(0)


def test_status_thresholds():
    assert drift.status(0.0) == "stable"
    assert drift.status(0.0999) == "stable"
    assert drift.status(0.10) == "moderate"
    assert drift.status(0.2499) == "moderate"
    assert drift.status(0.25) == "high"


def test_performance_status_thresholds():
    assert drift.performance_status(5.0, 4.0) == "ok"        # ratio 1.25 is still ok
    assert drift.performance_status(5.5, 4.0) == "watch"
    assert drift.performance_status(6.0, 4.0) == "watch"     # ratio 1.5
    assert drift.performance_status(6.1, 4.0) == "degraded"
    assert drift.performance_status(3.0, 0.0) == "unknown"


def test_reference_covers_every_feature_and_is_marked_synthetic():
    rng = random.Random(3)  # noqa: S311
    cols = {name: [float(rng.randint(0, 20)) for _ in range(300)] for name in FEATURE_COLUMNS}
    ref = build_reference(cols, version="v-test", dataset_sha256="abc")
    assert ref["synthetic"] is True and ref["n_rows"] == 300 and ref["version"] == "v-test"
    assert set(ref["features"]) == set(FEATURE_COLUMNS)


# ------------------------------------------------------------------------ simulation lab
def test_lab_is_deterministic_per_seed_and_differs_across_seeds():
    a, b = run(Scenario(days=8, seed=5)), run(Scenario(days=8, seed=5))
    assert a == b
    assert run(Scenario(days=8, seed=6)) != a


def test_lab_validates_bounds():
    for bad in ({"doctors": 0}, {"doctors": 7}, {"days": 4}, {"days": 31}, {"slot_minutes": 4},
                {"booked_share": 1.1}, {"walk_in_per_hour": -1}, {"mean_service_minutes": 50}):
        with pytest.raises(ValueError):
            validate(Scenario(**bad))
    validate(Scenario())


def test_more_walk_ins_do_not_shorten_waits():
    base = run(Scenario(days=15, walk_in_per_hour=0.5, seed=3))
    busy = run(Scenario(days=15, walk_in_per_hour=3.0, seed=3))
    assert busy.visits > base.visits
    assert busy.mean_wait_minutes >= base.mean_wait_minutes


def test_longer_consultations_raise_utilisation():
    short = run(Scenario(days=15, mean_service_minutes=8, seed=3))
    long = run(Scenario(days=15, mean_service_minutes=20, seed=3))
    assert long.utilisation > short.utilisation


def test_zero_walk_ins_is_supported():
    out = run(Scenario(days=6, walk_in_per_hour=0.0, seed=2))
    assert out.visits >= 0 and 0 <= out.utilisation <= 1.5
