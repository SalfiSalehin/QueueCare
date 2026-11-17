"""Phase 9 through the API: alternatives, drift, slot suggestions, simulation lab, explanations.
All data is synthetic. Drift tests point the service at a temporary model directory."""
from __future__ import annotations

import json
import random  # noqa: S311 - synthetic test data
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.services import drift_service, prediction_service, simulation_service
from ml.monitoring.reference import build_reference
from ml.preprocessing.features import FEATURE_COLUMNS
from tests.conftest import csrf, new_client, signup
from tests.integration.test_analytics import hours_ago, insert_visit, my_patient_id
from tests.integration.test_appointments import _open_all_week, setup_bookable
from tests.integration.test_clinic_management import mk_dept, mk_doctor, post
from tests.integration.test_queue import mk_patient, walk_in


@pytest.fixture
def q(owner_engine):
    return setup_bookable(owner_engine, slug="alpha", link_doctor=True)


def get(b, path, client=None, **params):
    return (client or b.env.admin).get(f"{b.env.base}/{path}", params=params)


# ============================================================ alternatives
def add_doctor(b, name, dept=None, schedule=True, **extra):
    d = mk_doctor(b.env, dept or b.doctor["department_id"], name, default_slot_minutes=30, buffer_minutes=0, **extra)
    if schedule:
        _open_all_week(b.env, d["id"])
    return d


def alts(b, doctor_id, client=None, **params):
    return get(b, f"doctors/{doctor_id}/alternatives", client or b.env.patient, **params)


def test_alternatives_list_other_doctors_with_slots_earliest_first(q):
    other = add_doctor(q, "Dr Other")
    body = alts(q, q.doctor["id"]).json()
    assert body["requested"]["doctor_id"] == q.doctor["id"] and body["requested"]["slots_in_range"] > 0
    assert [a["doctor_id"] for a in body["alternatives"]] == [other["id"]]
    starts = [a["earliest"]["starts_at"] for a in body["alternatives"]]
    assert starts == sorted(starts)


def test_alternatives_exclude_unavailable_doctors(q):
    add_doctor(q, "Dr NoSchedule", schedule=False)
    off = add_doctor(q, "Dr OffDuty")
    gone = add_doctor(q, "Dr Gone")
    assert q.env.admin.patch(f"{q.env.base}/doctors/{gone['id']}", json={"is_active": False},
                             headers=csrf(q.env.admin)).status_code == 200
    assert post(q.env.admin, f"{q.env.base}/doctors/{off['id']}/status", {"status": "OFF_DUTY"}).status_code == 200
    assert alts(q, q.doctor["id"]).json()["alternatives"] == []


def test_same_department_wins_ties(q):
    dept2 = mk_dept(q.env, name="Other", prefix="O")
    add_doctor(q, "Dr A Elsewhere", dept=dept2)
    mine = add_doctor(q, "Dr Z Same")
    ordered = alts(q, q.doctor["id"]).json()["alternatives"]
    assert ordered[0]["doctor_id"] == mine["id"] and ordered[0]["same_department"] is True


def test_alternatives_validation_and_access(q):
    assert alts(q, str(uuid.uuid4())).status_code == 404
    assert alts(q, q.doctor["id"], to="2000-01-01", **{"from": "2030-01-01"}).status_code == 422
    assert alts(q, q.doctor["id"], limit=0).status_code == 422
    assert alts(q, q.doctor["id"], new_client()).status_code == 401
    stranger = new_client()
    signup(stranger, "stranger@example.com")
    assert alts(q, q.doctor["id"], stranger).status_code == 404


def test_alternatives_never_cross_clinics(owner_engine, q):
    other_clinic = setup_bookable(owner_engine, slug="beta")
    assert [a["doctor_id"] for a in alts(q, q.doctor["id"]).json()["alternatives"]] == []
    assert other_clinic.doctor["id"] not in json.dumps(alts(q, q.doctor["id"]).json())


# ============================================================ explanations
def test_estimate_has_no_factors_without_a_model(q, monkeypatch, tmp_path):
    monkeypatch.setattr(prediction_service, "get_settings", lambda: SimpleNamespace(ml_model_dir=str(tmp_path / "x")))
    prediction_service._cache.clear()
    walk_in(q, mk_patient(q, "Ahead Person"))
    tok = walk_in(q, mk_patient(q, "Next Person")).json()
    body = get(q, f"queue/tokens/{tok['id']}/estimate", q.env.receptionist).json()
    assert body["source"] == "heuristic" and not body.get("factors") and body.get("typical_minutes") is None
    prediction_service._cache.clear()


def test_factors_are_for_staff_only(q, monkeypatch, quick_model_root):
    monkeypatch.setattr(prediction_service, "get_settings", lambda: SimpleNamespace(ml_model_dir=str(quick_model_root)))
    prediction_service._cache.clear()
    me = my_patient_id(q)
    walk_in(q, mk_patient(q, "Ahead One"))
    walk_in(q, mk_patient(q, "Ahead Two"))
    mine = walk_in(q, me).json()
    url = f"queue/tokens/{mine['id']}/estimate"
    staff = get(q, url, q.env.receptionist).json()
    assert staff["source"] == "model" and staff["factors"]
    assert all({"feature", "label", "minutes"} <= set(f) for f in staff["factors"])
    patient = get(q, url, q.env.patient).json()
    assert not patient.get("factors") and patient.get("typical_minutes") is None
    prediction_service._cache.clear()


# ============================================================ drift
def make_model_dir(tmp_path, *, with_reference=True, mae=4.0):
    version = "lgbm-test-v1"
    (tmp_path / version).mkdir(parents=True)
    (tmp_path / "ACTIVE").write_text(version + "\n")
    (tmp_path / version / "bundle.json").write_text(json.dumps({"version": version, "test_metrics": {"point": {"mae": mae}}}))
    rng = random.Random(1)  # noqa: S311
    cols = {n: [float(rng.randint(0, 8)) for _ in range(500)] for n in FEATURE_COLUMNS}
    if with_reference:
        (tmp_path / version / "reference.json").write_text(
            json.dumps(build_reference(cols, version=version, dataset_sha256="x")))
    return version, cols


def seed_logs(owner_engine, b, version, n, value_of, abs_error=None):
    with owner_engine.connect() as c:
        mv = c.execute(text(
            "insert into model_versions (version, algorithm, artifact_ref, trained_at, is_active) "
            "values (:v, 'test', 'x', now(), true) on conflict (version) do update set version = excluded.version "
            "returning id"), {"v": version}).scalar()
        for i in range(n):
            snap = {name: value_of(name, i) for name in FEATURE_COLUMNS}
            c.execute(text(
                "insert into prediction_logs (clinic_id, model_version_id, pred_lower, pred_median, pred_upper, "
                "abs_error, actual_wait, feature_snapshot) values (:c, :m, 0, 5, 10, :e, :w, cast(:s as jsonb))"),
                {"c": b.env.cid, "m": mv, "e": abs_error, "w": None if abs_error is None else 5.0, "s": json.dumps(snap)})
        c.commit()


@pytest.fixture
def model_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(drift_service, "get_settings", lambda: SimpleNamespace(ml_model_dir=str(tmp_path)))
    return tmp_path


def test_drift_reports_no_model_and_no_reference(q, model_dir):
    assert get(q, "analytics/drift").json()["status"] == "no_model"
    make_model_dir(model_dir, with_reference=False)
    body = get(q, "analytics/drift").json()
    assert body["status"] == "no_reference" and "ml.monitoring.reference" in body["note"]


def test_drift_needs_enough_live_predictions(q, model_dir, owner_engine):
    version, _ = make_model_dir(model_dir)
    seed_logs(owner_engine, q, version, 10, lambda n, i: 1.0)
    body = get(q, "analytics/drift").json()
    assert body["status"] == "insufficient_data" and body["samples"] == 10 and body["features"] == []


def test_drift_flags_shifted_inputs_and_is_quiet_for_matching_ones(q, model_dir, owner_engine):
    version, _ = make_model_dir(model_dir)
    seed_logs(owner_engine, q, version, 150, lambda n, i: float(random.Random(f"{n}{i}").randint(0, 8)))  # noqa: S311
    ok = get(q, "analytics/drift").json()
    assert ok["status"] == "ok" and ok["overall"] in ("stable", "moderate")
    with owner_engine.connect() as c:
        c.execute(text("delete from prediction_logs"))
        c.commit()
    seed_logs(owner_engine, q, version, 150, lambda n, i: 500.0)
    shifted = get(q, "analytics/drift").json()
    assert shifted["overall"] == "high" and shifted["features"][0]["psi"] > 0.25


def test_drift_performance_compares_with_the_training_error(q, model_dir, owner_engine):
    version, _ = make_model_dir(model_dir, mae=4.0)
    seed_logs(owner_engine, q, version, 120, lambda n, i: 1.0, abs_error=10.0)
    perf = get(q, "analytics/drift").json()["performance"]
    assert perf["status"] == "degraded" and perf["recent_mae_minutes"] == 10.0 and perf["reference_mae_minutes"] == 4.0


def test_drift_is_admin_only_validated_and_clinic_scoped(q, model_dir, owner_engine):
    version, _ = make_model_dir(model_dir)
    seed_logs(owner_engine, q, version, 120, lambda n, i: 1.0)
    for client in (q.env.receptionist, q.env.doctor, q.env.patient):
        assert get(q, "analytics/drift", client).status_code == 403
    assert get(q, "analytics/drift", new_client()).status_code == 401
    assert get(q, "analytics/drift", days=0).status_code == 422
    assert get(q, "analytics/drift", days=91).status_code == 422
    other = setup_bookable(owner_engine, slug="beta")
    assert get(other, "analytics/drift").json()["samples"] == 0          # alpha's logs are invisible to beta


# ============================================================ scheduling suggestions
def suggestions(b, client=None, **params):
    return get(b, "analytics/scheduling-suggestions", client, **params)


def test_suggestions_need_enough_consultations(q, owner_engine):
    pid = my_patient_id(q)
    for _ in range(5):
        insert_visit(owner_engine, q, pid, hours_ago(5), 0, 20)
    item = suggestions(q).json()["items"][0]
    assert item["status"] == "insufficient_data" and item["suggested_slot_minutes"] is None and item["consultations"] == 5


def test_long_consultations_suggest_a_longer_slot(q, owner_engine):
    pid = my_patient_id(q)
    for _ in range(35):
        insert_visit(owner_engine, q, pid, hours_ago(5), 0, 40)
    item = suggestions(q).json()["items"][0]
    assert item["status"] == "lengthen" and item["current_slot_minutes"] == 30
    assert item["suggested_slot_minutes"] == 40 and item["overrun_share_now"] == 1.0
    assert item["advice"]


def test_short_consultations_suggest_a_shorter_slot_and_window_is_respected(q, owner_engine):
    pid = my_patient_id(q)
    for _ in range(35):
        insert_visit(owner_engine, q, pid, hours_ago(5), 0, 10)
    assert suggestions(q).json()["items"][0]["status"] == "shorten"
    assert suggestions(q, days=7).json()["items"][0]["status"] == "shorten"
    # visits older than the window do not count
    with owner_engine.connect() as c:
        c.execute(text("update consultations set started_at = :t"), {"t": datetime.now(UTC) - timedelta(days=60)})
        c.commit()
    assert suggestions(q, days=30).json()["items"][0]["status"] == "insufficient_data"


def test_suggestions_are_admin_only_validated_and_isolated(q, owner_engine):
    for client in (q.env.receptionist, q.env.doctor, q.env.patient):
        assert suggestions(q, client).status_code == 403
    assert suggestions(q, new_client()).status_code == 401
    assert suggestions(q, days=6).status_code == 422
    assert suggestions(q, days=366).status_code == 422
    other = setup_bookable(owner_engine, slug="beta")
    pid = my_patient_id(q)
    for _ in range(35):
        insert_visit(owner_engine, q, pid, hours_ago(5), 0, 40)
    assert [i["status"] for i in suggestions(other).json()["items"]] == ["insufficient_data"]


# ============================================================ simulation lab
def simulate(b, scenarios, client=None):
    return post(client or b.env.admin, f"{b.env.base}/simulation", {"scenarios": scenarios})


def test_simulation_is_deterministic_labelled_synthetic_and_reports_deltas(q):
    body = simulate(q, [{"name": "Now", "days": 6, "seed": 4},
                        {"name": "Busier", "days": 6, "seed": 4, "walk_in_per_hour": 3}]).json()
    assert body["synthetic"] is True and "synthetic" in body["note"].lower()
    first, second = body["results"]
    assert first["mean_wait_change_minutes"] is None
    assert second["mean_wait_change_minutes"] == pytest.approx(
        second["outcome"]["mean_wait_minutes"] - first["outcome"]["mean_wait_minutes"], abs=0.01)
    again = simulate(q, [{"name": "Now", "days": 6, "seed": 4}]).json()
    assert again["results"][0]["outcome"] == first["outcome"]


def test_simulation_rejects_bad_input(q):
    assert simulate(q, []).status_code == 422
    assert simulate(q, [{}, {}, {}, {}]).status_code == 422
    assert simulate(q, [{"doctors": 7}]).status_code == 422
    assert simulate(q, [{"days": 31}]).status_code == 422
    assert simulate(q, [{"walk_in_per_hour": 9}]).status_code == 422
    assert simulate(q, [{"unknown_field": 1}]).status_code == 422


def test_simulation_is_admin_only(q):
    for client in (q.env.receptionist, q.env.doctor, q.env.patient):
        assert simulate(q, [{"days": 5}], client).status_code == 403
    assert simulate(q, [{"days": 5}], new_client()).status_code in (401, 403)   # CSRF may answer first


def test_simulation_is_bounded_by_a_concurrency_limit(q, monkeypatch):
    class Full:
        def acquire(self, blocking=True):
            return False

        def release(self):
            raise AssertionError("must not release a slot it never took")

    monkeypatch.setattr(simulation_service, "_slots", Full())
    r = simulate(q, [{"days": 5}])
    assert r.status_code == 429 and r.json()["error"]["code"]
