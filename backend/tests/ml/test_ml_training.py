"""Training pipeline and predictor. These need LightGBM/pandas/scikit-learn (installed in the backend
Docker image) and are skipped where those libraries are absent.

A tiny model is trained on synthetic data. The tests check behaviour and safety properties; they
deliberately assert NO accuracy number (accuracy is reported by `ml.training.run`, as measured).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from ml.prediction.predictor import ACTIVE_POINTER, ModelLoadError, Predictor  # noqa: E402
from ml.preprocessing.features import FEATURE_COLUMNS, TARGET, QueueSnapshot, features_from_snapshot  # noqa: E402
from ml.training.promote import promote  # noqa: E402
from ml.training.run import run_pipeline  # noqa: E402


def version_dir(root: Path) -> Path:
    return root / (root / ACTIVE_POINTER).read_text().strip()


def snapshot(**over) -> dict[str, float]:
    base = dict(arrival_minute_of_day=630.0, day_of_week=2, is_scheduled=False, lateness_min=0.0, priority=0,
                n_scheduled_ahead=0, n_walkin_ahead=0, sched_slot_minutes_ahead=0.0, in_service=True,
                elapsed_in_service_min=3.0, doctor_recent_mean_service=12.0, doctor_recent_p80_service=17.0,
                slot_minutes=15.0, arrivals_last_30min=2)
    base.update(over)
    return features_from_snapshot(QueueSnapshot(**base))


# --------------------------------------------------------------------- artifacts
def test_training_writes_the_expected_artifacts_and_no_pickles(quick_model_root):
    d = version_dir(quick_model_root)
    for name in ("bundle.json", "metrics.json", "report.md", "q10.txt", "q50.txt", "q90.txt"):
        assert (d / name).is_file(), name
    assert not [p for p in d.rglob("*") if p.suffix in {".pkl", ".pickle", ".joblib"}]


def test_metrics_are_marked_synthetic_and_the_split_is_chronological(quick_model_root):
    m = json.loads((version_dir(quick_model_root) / "metrics.json").read_text())
    assert m["synthetic"] is True and m["quick"] is True
    s = m["split"]
    assert s["train"]["last_day"] < s["val"]["first_day"] <= s["val"]["last_day"] < s["test"]["first_day"]
    assert min(s[k]["rows"] for k in s) > 0
    for key in ("baseline_global_median", "baseline_naive_work_ahead", "ridge", "random_forest",
                "gradient_boosting", "lightgbm_l2", "lightgbm_median_q50"):
        assert "mae" in m["point_models_test"][key]
    assert set(m["interval_models_test"]) >= {"constant_width_baseline", "lightgbm_quantile_calibrated"}


def test_report_states_that_the_data_is_synthetic(quick_model_root):
    report = (version_dir(quick_model_root) / "report.md").read_text().lower()
    assert "synthetic" in report


def test_bundle_lists_exactly_the_serving_features(quick_model_root):
    b = json.loads((version_dir(quick_model_root) / "bundle.json").read_text())
    assert tuple(b["features"]) == FEATURE_COLUMNS and b["synthetic"] is True


# ------------------------------------------------------------------ reproducibility
def test_same_seed_gives_identical_metrics_and_a_different_seed_does_not(quick_model_root, tmp_path):
    first = (version_dir(quick_model_root) / "metrics.json").read_text()
    again = run_pipeline(seed=7, out_root=tmp_path / "a", quick=True, work_dir=tmp_path / "da")
    assert (again / "metrics.json").read_text() == first
    other = run_pipeline(seed=8, out_root=tmp_path / "b", quick=True, work_dir=tmp_path / "db")
    assert (other / "metrics.json").read_text() != first


# ---------------------------------------------------------------------- leakage
def test_a_model_trained_on_shuffled_labels_learns_nothing_useful(tmp_path):
    """If features secretly contained the answer, shuffling the labels would still not hurt validation
    much. A model fitted to shuffled labels must be no better than predicting the global median."""
    import lightgbm as lgb
    import numpy as np

    from ml.data_generation.generate_dataset import write_dataset
    from ml.training.data import load_dataset, temporal_split

    write_dataset(tmp_path, seed=5, days=40, doctors=4)
    split = temporal_split(load_dataset(tmp_path / "synthetic_visits.csv.gz"))
    cols = list(FEATURE_COLUMNS)
    shuffled = split.train[TARGET].sample(frac=1.0, random_state=0).to_numpy()
    booster = lgb.train({"objective": "regression_l1", "verbosity": -1, "seed": 0, "num_leaves": 15},
                        lgb.Dataset(split.train[cols], shuffled), num_boost_round=60)
    pred = booster.predict(split.test[cols])
    y = split.test[TARGET].to_numpy()
    model_mae = float(np.abs(y - pred).mean())
    baseline_mae = float(np.abs(y - float(np.median(split.train[TARGET]))).mean())
    assert model_mae >= 0.9 * baseline_mae


def test_the_dataset_loader_refuses_rows_not_marked_synthetic(tmp_path):
    import gzip

    from ml.data_generation.generate_dataset import write_dataset
    from ml.training.data import load_dataset

    write_dataset(tmp_path, seed=1, days=12, doctors=2)
    path = tmp_path / "synthetic_visits.csv.gz"
    text = gzip.decompress(path.read_bytes()).decode().replace(",True", ",False")
    path.write_bytes(gzip.compress(text.encode()))
    with pytest.raises(ValueError, match="synthetic"):
        load_dataset(path)


# ---------------------------------------------------------------------- predictor
@pytest.fixture(scope="module")
def predictor(quick_model_root) -> Predictor:
    return Predictor.load(quick_model_root)


def test_active_pointer_selects_the_model(quick_model_root, predictor):
    assert Predictor.active_version(quick_model_root) == predictor.version
    assert Predictor.active_version(quick_model_root / "missing") is None


def test_estimates_are_ordered_non_negative_and_finite(predictor):
    for ahead in (0, 1, 3, 6, 10):
        for hour in (9.0, 12.5, 16.0):
            e = predictor.predict(snapshot(n_walkin_ahead=ahead, arrival_minute_of_day=hour * 60))
            assert 0 <= e.lower <= e.median <= e.upper
            assert e.model_version == predictor.version


def test_more_people_ahead_means_a_longer_median_wait_overall(predictor):
    """Coarse trend only: strict monotonicity is not guaranteed for quantile objectives."""
    short = predictor.predict(snapshot(n_walkin_ahead=0, in_service=False, elapsed_in_service_min=0)).median
    long = predictor.predict(snapshot(n_walkin_ahead=9)).median
    assert long > short


def test_predict_rejects_wrong_or_non_finite_features(predictor):
    good = snapshot()
    reordered = dict(reversed(list(good.items())))
    with pytest.raises(ValueError):
        predictor.predict(reordered)
    with pytest.raises(ValueError):
        predictor.predict({**good, "people_ahead": float("nan")})
    with pytest.raises(ValueError):
        predictor.predict({k: v for k, v in good.items() if k != "priority"})


def test_a_model_trained_on_different_features_is_refused(quick_model_root, tmp_path):
    root = tmp_path / "models"
    shutil.copytree(quick_model_root, root)
    d = version_dir(root)
    bundle = json.loads((d / "bundle.json").read_text())
    bundle["features"] = bundle["features"][:-1]
    (d / "bundle.json").write_text(json.dumps(bundle))
    with pytest.raises(ModelLoadError, match="different features"):
        Predictor.load(root)


def test_version_names_cannot_escape_the_model_directory(quick_model_root):
    for bad in ("../x", "a/b", "..\\x", ".hidden"):       # "" means "the active version", not a path
        with pytest.raises(ModelLoadError):
            Predictor.load(quick_model_root, bad)


def test_a_bundle_that_names_another_version_is_refused(quick_model_root, tmp_path):
    root = tmp_path / "models"
    shutil.copytree(quick_model_root, root)
    d = version_dir(root)
    bundle = json.loads((d / "bundle.json").read_text())
    bundle["version"] = "something-else"
    (d / "bundle.json").write_text(json.dumps(bundle))
    with pytest.raises(ModelLoadError):
        Predictor.load(root)


# ---------------------------------------------------------------------- promotion
def test_promotion_is_explicit_and_validated(quick_model_root, tmp_path):
    root = tmp_path / "models"
    shutil.copytree(quick_model_root, root)
    (root / ACTIVE_POINTER).unlink()
    assert Predictor.active_version(root) is None             # training alone never serves a model
    version = next(p.name for p in root.iterdir() if p.is_dir())
    promote(version, root)
    assert Predictor.active_version(root) == version
    with pytest.raises(SystemExit):
        promote("no-such-version", root)
