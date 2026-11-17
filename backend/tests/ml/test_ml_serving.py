"""Wait-time estimates through the API: model vs honest fallback, who sees what, prediction logging.

The model used here is a tiny one trained on synthetic data (see conftest); no accuracy is asserted.
"""
from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.services import prediction_service
from tests.integration.test_appointments import my_patient_id, setup_bookable
from tests.integration.test_queue import act, mk_patient, walk_in


@pytest.fixture
def q(owner_engine):
    return setup_bookable(owner_engine, slug="alpha", link_doctor=True)


def point_at(monkeypatch, directory) -> None:
    monkeypatch.setattr(prediction_service, "get_settings", lambda: SimpleNamespace(ml_model_dir=str(directory)))
    prediction_service._cache.clear()


@pytest.fixture
def with_model(monkeypatch, quick_model_root):
    point_at(monkeypatch, quick_model_root)
    yield quick_model_root
    prediction_service._cache.clear()


@pytest.fixture
def without_model(monkeypatch, tmp_path):
    point_at(monkeypatch, tmp_path / "empty")
    yield
    prediction_service._cache.clear()


def estimate(b, token_id: str, client=None):
    return (client or b.env.receptionist).get(f"{b.env.base}/queue/tokens/{token_id}/estimate")


def logs(owner_engine) -> list:
    with owner_engine.connect() as c:
        return list(c.execute(text(
            "SELECT token_id, pred_lower, pred_median, pred_upper, actual_wait, abs_error, model_version_id "
            "FROM prediction_logs ORDER BY created_at")))


# ----------------------------------------------------------------- no model: honest fallback
def test_without_a_model_the_estimate_is_a_labelled_heuristic_with_no_range(q, without_model, owner_engine):
    first = walk_in(q, mk_patient(q, "First Person")).json()
    second = walk_in(q, mk_patient(q, "Second Person")).json()
    body = estimate(q, second["id"]).json()
    assert body["source"] == "heuristic" and body["model_version"] is None
    assert body["lower_minutes"] is None and body["upper_minutes"] is None
    assert body["median_minutes"] > 0 and "no trained model" in body["note"].lower()
    assert estimate(q, first["id"]).json()["median_minutes"] == 0.0     # nobody ahead
    assert logs(owner_engine) == []                                       # nothing is logged without a model


# --------------------------------------------------------------------------- with a model
def test_staff_get_the_range_and_patients_get_only_the_median(q, with_model):
    me = my_patient_id(q)
    walk_in(q, mk_patient(q, "Ahead One"))
    walk_in(q, mk_patient(q, "Ahead Two"))
    mine = walk_in(q, me).json()
    staff = estimate(q, mine["id"]).json()
    assert staff["source"] == "model" and staff["model_version"]
    assert 0 <= staff["lower_minutes"] <= staff["median_minutes"] <= staff["upper_minutes"]
    assert "synthetic" in staff["note"].lower()
    patient = estimate(q, mine["id"], q.env.patient).json()
    assert patient["source"] == "model" and patient["median_minutes"] == staff["median_minutes"]
    assert patient["lower_minutes"] is None and patient["upper_minutes"] is None
    doctor = estimate(q, mine["id"], q.env.doctor).json()
    assert doctor["lower_minutes"] is not None


def test_a_patient_cannot_read_someone_elses_estimate(q, with_model):
    my_patient_id(q)
    stranger = walk_in(q, mk_patient(q, "Someone Else")).json()
    assert estimate(q, stranger["id"], q.env.patient).status_code == 404


def test_unknown_token_is_404_and_unauthenticated_is_401(q, with_model):
    import uuid

    from tests.conftest import new_client
    assert estimate(q, str(uuid.uuid4())).status_code == 404
    assert new_client().get(f"{q.env.base}/queue/tokens/{uuid.uuid4()}/estimate").status_code == 401


def test_a_token_that_is_not_waiting_has_nothing_to_estimate(q, with_model):
    tok = walk_in(q, mk_patient(q)).json()
    assert act(q, tok["id"], "call").status_code == 200
    body = estimate(q, tok["id"]).json()
    assert body["source"] == "not_waiting" and body["median_minutes"] is None


# ------------------------------------------------------------------ the prediction log
def test_arrival_prediction_is_logged_and_completed_with_the_actual_wait(q, with_model, owner_engine):
    tok = walk_in(q, mk_patient(q)).json()
    rows = logs(owner_engine)
    assert len(rows) == 1
    assert str(rows[0].token_id) == tok["id"]
    assert 0 <= rows[0].pred_lower <= rows[0].pred_median <= rows[0].pred_upper
    assert rows[0].actual_wait is None
    assert act(q, tok["id"], "call").status_code == 200
    assert act(q, tok["id"], "start").status_code == 200
    done = logs(owner_engine)[0]
    assert done.actual_wait is not None and done.actual_wait >= 0
    assert done.abs_error == pytest.approx(abs(done.pred_median - done.actual_wait))


def test_the_model_version_is_registered_once_and_active(q, with_model, owner_engine):
    walk_in(q, mk_patient(q, "One Person"))
    walk_in(q, mk_patient(q, "Two People"))
    with owner_engine.connect() as c:
        versions = list(c.execute(text("SELECT version, is_active, algorithm FROM model_versions")))
    assert len(versions) == 1 and versions[0].is_active
    assert versions[0].version == prediction_service.get_predictor(str(with_model)).version
    assert len({r.model_version_id for r in logs(owner_engine)}) == 1


# ---------------------------------------------------------------------- failure isolation
def test_a_broken_model_never_blocks_the_queue(q, monkeypatch, quick_model_root, tmp_path, owner_engine):
    root = tmp_path / "models"
    shutil.copytree(quick_model_root, root)
    version = (root / "ACTIVE").read_text().strip()
    bundle = json.loads((root / version / "bundle.json").read_text())
    bundle["features"] = bundle["features"][:-1]               # simulates a train/serve mismatch
    (root / version / "bundle.json").write_text(json.dumps(bundle))
    point_at(monkeypatch, root)
    tok = walk_in(q, mk_patient(q))
    assert tok.status_code == 201                                # joining the queue still works
    body = estimate(q, tok.json()["id"]).json()
    assert body["source"] == "heuristic"                         # and the estimate is honest about the fallback
    assert logs(owner_engine) == []


def test_a_failing_prediction_is_swallowed_and_does_not_poison_the_transaction(q, with_model, monkeypatch,
                                                                                 owner_engine):
    def boom(self, features):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr("ml.prediction.predictor.Predictor.predict", boom)
    tok = walk_in(q, mk_patient(q))
    assert tok.status_code == 201 and tok.json()["status"] == "WAITING"
    assert logs(owner_engine) == []
    assert estimate(q, tok.json()["id"]).json()["source"] == "heuristic"
