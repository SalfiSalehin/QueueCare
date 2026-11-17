"""SHAP-style explanations and the training reference. Needs LightGBM, so it runs in Docker only."""
from __future__ import annotations

import json

import pytest

from ml.prediction.predictor import Predictor
from ml.preprocessing.features import FEATURE_COLUMNS


def _features(**over) -> dict[str, float]:
    base = {name: 0.0 for name in FEATURE_COLUMNS}
    base.update(over)
    return base


def test_explanation_is_additive_and_covers_every_feature(quick_model_root):
    p = Predictor.load(quick_model_root)
    for ahead in (0, 3, 8):
        e = p.explain(_features(people_ahead=ahead, n_waiting_ahead=ahead, n_scheduled_ahead=ahead,
                                doctor_recent_mean_service=12.0))
        assert set(e.contributions) == set(FEATURE_COLUMNS)
        assert e.raw_minutes == pytest.approx(e.base_minutes + sum(e.contributions.values()), abs=1e-9)


def test_more_people_ahead_pushes_the_estimate_up(quick_model_root):
    p = Predictor.load(quick_model_root)
    few = p.explain(_features(people_ahead=1, n_waiting_ahead=1, n_scheduled_ahead=1, doctor_recent_mean_service=12.0))
    many = p.explain(_features(people_ahead=6, n_waiting_ahead=6, n_scheduled_ahead=6, doctor_recent_mean_service=12.0))
    assert many.raw_minutes > few.raw_minutes
    assert many.contributions["people_ahead"] > few.contributions["people_ahead"]


def test_training_writes_a_reference_for_every_feature(quick_model_root):
    version = Predictor.active_version(quick_model_root)
    ref = json.loads((quick_model_root / version / "reference.json").read_text())
    assert ref["version"] == version and ref["synthetic"] is True
    assert set(ref["features"]) == set(FEATURE_COLUMNS)
    for spec in ref["features"].values():
        assert sum(spec["proportions"]) == pytest.approx(1.0, abs=1e-3)
