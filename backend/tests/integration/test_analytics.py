"""Phase 8: clinic analytics. Numbers are checked against hand-computed values from rows inserted directly,
isolation between clinics is checked, and access is limited to clinic admins. All data is synthetic."""
from __future__ import annotations

import itertools
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import csrf, new_client
from tests.integration.test_appointments import Bk, book, insert_appt, setup_bookable, slots

_seq = itertools.count(1)


def my_patient_id(b: Bk) -> str:
    """Create the patient profile by booking and cancelling the LAST bookable slot (far in the future), so the
    cancelled appointment can never fall inside an analytics range, whatever time of day the tests run."""
    c = b.env.patient
    r = book(b, slots(b, c)[-1]["starts_at"], c)
    assert r.status_code == 201, r.text
    assert c.post(f"{b.env.base}/appointments/{r.json()['id']}/cancel", headers=csrf(c)).status_code == 200
    return r.json()["patient_id"]


@pytest.fixture
def q(owner_engine):
    return setup_bookable(owner_engine, slug="alpha")


def api(b: Bk, path: str, client=None, **params):
    return (client or b.env.admin).get(f"{b.env.base}/analytics/{path}", params=params)


def insert_visit(owner_engine, b: Bk, patient_id: str, arrived_at: datetime, wait: int, duration: int,
                 source: str = "WALK_IN") -> None:
    """A finished visit: a COMPLETED token plus its consultation (waited `wait` min, then `duration` min)."""
    token_id, n = str(uuid.uuid4()), next(_seq)
    started = arrived_at + timedelta(minutes=wait)
    with owner_engine.connect() as c:
        c.execute(text(
            "insert into queue_tokens (id, clinic_id, doctor_id, patient_id, queue_date, prefix, sequence_no, "
            "token_label, source, status, arrived_at, started_at, completed_at) values "
            "(:i, :c, :d, :p, :qd, 'G', :n, :lbl, :src, 'COMPLETED', :a, :s, :e)"),
            {"i": token_id, "c": b.env.cid, "d": b.doctor["id"], "p": patient_id, "qd": arrived_at.date(), "n": n,
             "lbl": f"G-{n:03d}", "src": source, "a": arrived_at, "s": started, "e": started + timedelta(minutes=duration)})
        c.execute(text(
            "insert into consultations (clinic_id, token_id, doctor_id, started_at, ended_at, duration_minutes, "
            "actual_wait_minutes) values (:c, :t, :d, :s, :e, :dur, :w)"),
            {"c": b.env.cid, "t": token_id, "d": b.doctor["id"], "s": started,
             "e": started + timedelta(minutes=duration), "dur": duration, "w": wait})


def hours_ago(h: float) -> datetime:
    return (datetime.now(UTC) - timedelta(hours=h)).replace(microsecond=0)


def seed(owner_engine, b: Bk) -> str:
    pid = my_patient_id(b)
    for i, status in enumerate(("COMPLETED", "COMPLETED", "COMPLETED", "NO_SHOW", "CANCELLED")):
        insert_appt(owner_engine, b, hours_ago(2 + i), pid, status=status)
    for wait, duration in ((0, 10), (10, 10), (20, 20), (30, 20)):
        insert_visit(owner_engine, b, pid, hours_ago(3), wait, duration)
    return pid


# =================================================================== access
def test_only_clinic_admins_can_read_analytics(q):
    for path in ("overview", "doctors", "load", "prediction-accuracy"):
        assert api(q, path).status_code == 200
        for who in (q.env.receptionist, q.env.doctor, q.env.patient):
            assert api(q, path, who).status_code == 403, (path, who)
        assert api(q, path, new_client()).status_code == 401


def test_another_clinics_admin_cannot_read_this_clinics_analytics(owner_engine, q):
    beta = setup_bookable(owner_engine, slug="beta")
    assert beta.env.admin.get(f"{q.env.base}/analytics/overview").status_code == 404


def test_date_ranges_are_validated(q):
    assert api(q, "overview", start_date="2026-02-01", end_date="2026-01-01").status_code == 422
    assert api(q, "overview", start_date="2025-01-01", end_date="2026-06-01").status_code == 422   # > 366 days
    assert api(q, "overview", start_date="not-a-date").status_code == 422
    ok = api(q, "overview", start_date="2026-01-01", end_date="2026-01-01").json()
    assert len(ok["daily"]) == 1


# ================================================================ overview
def test_an_empty_clinic_reports_zeros_and_no_rates(q):
    body = api(q, "overview").json()
    assert body["appointments_total"] == 0 and body["tokens_total"] == 0
    assert body["no_show_rate"] is None and body["cancellation_rate"] is None and body["walk_in_share"] is None
    assert body["wait_minutes"]["n"] == 0 and body["wait_minutes"]["mean"] is None
    assert len(body["daily"]) == 30


def test_overview_numbers_match_hand_computed_values(owner_engine, q):
    seed(owner_engine, q)
    body = api(q, "overview").json()
    assert body["appointments_total"] == 5
    assert body["appointments_by_status"] == {"COMPLETED": 3, "NO_SHOW": 1, "CANCELLED": 1}
    assert body["no_show_rate"] == 0.25                    # 1 / (3 completed + 1 no-show)
    assert body["cancellation_rate"] == 0.2                # 1 / 5
    assert body["tokens_total"] == 4 and body["tokens_by_status"] == {"COMPLETED": 4}
    assert body["walk_in_share"] == 1.0
    wait = body["wait_minutes"]                            # waits 0, 10, 20, 30
    assert (wait["n"], wait["mean"], wait["p50"], wait["max"]) == (4, 15.0, 15.0, 30.0)
    assert wait["p90"] == 27.0                             # linear interpolation: 20 + 0.7 * 10
    dur = body["consultation_minutes"]                     # 10, 10, 20, 20
    assert (dur["n"], dur["mean"], dur["p50"], dur["max"]) == (4, 15.0, 15.0, 20.0)
    assert sum(d["appointments"] for d in body["daily"]) == 5
    assert sum(d["arrivals"] for d in body["daily"]) == 4 and sum(d["consultations"] for d in body["daily"]) == 4


def test_only_rows_inside_the_range_are_counted(owner_engine, q):
    pid = my_patient_id(q)
    insert_appt(owner_engine, q, datetime.now(UTC) - timedelta(days=100), pid, status="COMPLETED")
    insert_appt(owner_engine, q, hours_ago(1), pid, status="COMPLETED")
    assert api(q, "overview").json()["appointments_total"] == 1
    wide = api(q, "overview", start_date=(datetime.now(UTC) - timedelta(days=120)).date().isoformat()).json()
    assert wide["appointments_total"] == 2


def test_analytics_never_include_other_clinics_data(owner_engine, q):
    seed(owner_engine, q)
    beta = setup_bookable(owner_engine, slug="beta")
    pid = my_patient_id(beta)
    for i in range(3):
        insert_appt(owner_engine, beta, hours_ago(2 + i), pid, status="COMPLETED")
        insert_visit(owner_engine, beta, pid, hours_ago(5), 40, 15)
    a, b = api(q, "overview").json(), api(beta, "overview").json()
    assert a["appointments_total"] == 5 and a["wait_minutes"]["max"] == 30.0
    assert b["appointments_total"] == 3 and b["wait_minutes"]["mean"] == 40.0
    for path in ("doctors", "load", "prediction-accuracy"):
        assert api(q, path).status_code == 200 and api(beta, path).status_code == 200


def test_analytics_contain_no_patient_identity(owner_engine, q):
    seed(owner_engine, q)
    blob = json.dumps([api(q, p).json() for p in ("overview", "doctors", "load", "prediction-accuracy")])
    for needle in ("patient-alpha", "@example.com", "full_name", "patient_id"):
        assert needle not in blob


# ============================================================== doctors
def test_doctor_utilisation_uses_schedule_time_off_and_bookings(owner_engine, q):
    seed(owner_engine, q)
    today = datetime.now(UTC).date()
    day_start = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=1)
    with owner_engine.connect() as c:                          # yesterday is a day off
        c.execute(text("insert into doctor_time_off (clinic_id, doctor_id, period) values "
                       "(:c, :d, tstzrange(:a, :b))"),
                  {"c": q.env.cid, "d": q.doctor["id"], "a": day_start, "b": day_start + timedelta(days=1)})
    start = (today - timedelta(days=6)).isoformat()
    body = api(q, "doctors", start_date=start, end_date=today.isoformat()).json()
    row = next(r for r in body["items"] if r["doctor_id"] == q.doctor["id"])
    assert row["scheduled_minutes"] == 6 * 180                  # 7 days x 09:00-12:00, minus the day off
    assert row["booked_minutes"] == 4 * 30                      # 4 non-cancelled appointments of 30 min
    assert row["consultation_minutes"] == 60 and row["patients_seen"] == 4
    assert row["avg_wait_minutes"] == 15.0
    assert row["booked_utilisation"] == round(120 / 1080, 4)
    assert row["busy_utilisation"] == round(60 / 1080, 4)


def test_a_doctor_without_a_schedule_has_no_utilisation_ratio(owner_engine, q):
    with owner_engine.connect() as c:
        c.execute(text("delete from doctor_schedules where clinic_id=:c"), {"c": q.env.cid})
    row = next(r for r in api(q, "doctors").json()["items"] if r["doctor_id"] == q.doctor["id"])
    assert row["scheduled_minutes"] == 0 and row["booked_utilisation"] is None and row["busy_utilisation"] is None


# ================================================================== load
def test_load_groups_arrivals_by_clinic_local_hour_and_weekday(owner_engine, q):
    pid = my_patient_id(q)
    day = datetime.now(UTC).date() - timedelta(days=1)
    at = lambda h, m: datetime(day.year, day.month, day.day, h, m, tzinfo=UTC)  # noqa: E731
    insert_visit(owner_engine, q, pid, at(10, 5), 10, 10)
    insert_visit(owner_engine, q, pid, at(10, 40), 30, 10)
    insert_visit(owner_engine, q, pid, at(14, 0), 0, 10)
    body = api(q, "load").json()
    by_hour = {h["hour"]: h for h in body["by_hour"]}
    assert by_hour[10]["arrivals"] == 2 and by_hour[10]["avg_wait_minutes"] == 20.0
    assert by_hour[14]["arrivals"] == 1 and by_hour[14]["avg_wait_minutes"] == 0.0
    weekdays = {w["weekday"]: w["arrivals"] for w in body["by_weekday"]}
    assert len(weekdays) == 7 and weekdays[day.weekday()] == 3 and sum(weekdays.values()) == 3


def test_load_respects_the_clinic_timezone(owner_engine, q):
    with owner_engine.connect() as c:
        c.execute(text("update clinics set timezone='Asia/Dhaka' where id=:c"), {"c": q.env.cid})
    pid = my_patient_id(q)
    day = datetime.now(UTC).date() - timedelta(days=1)
    insert_visit(owner_engine, q, pid, datetime(day.year, day.month, day.day, 4, 0, tzinfo=UTC), 0, 5)
    hours = {h["hour"] for h in api(q, "load").json()["by_hour"]}
    assert hours == {10}                                         # 04:00 UTC is 10:00 in Dhaka


# ========================================================= prediction accuracy
def add_prediction(owner_engine, q, version_id: str, median, lower, upper, actual, naive) -> None:
    with owner_engine.connect() as c:
        c.execute(text(
            "insert into prediction_logs (clinic_id, model_version_id, pred_lower, pred_median, pred_upper, "
            "actual_wait, abs_error, feature_snapshot) values (:c, :m, :lo, :md, :up, :a, :e, cast(:f as jsonb))"),
            {"c": q.env.cid, "m": version_id, "lo": lower, "md": median, "up": upper, "a": actual,
             "e": abs(median - actual), "f": json.dumps({"expected_work_ahead_min": naive})})


def add_version(owner_engine, version="lgbm-test-1") -> str:
    vid = str(uuid.uuid4())
    with owner_engine.connect() as c:
        c.execute(text("insert into model_versions (id, version, algorithm, artifact_ref, trained_at) "
                       "values (:i, :v, 'lightgbm-quantile', 'ml/models/x', now())"), {"i": vid, "v": version})
    return vid


def test_with_no_predictions_the_accuracy_report_says_so(q):
    body = api(q, "prediction-accuracy").json()
    assert body["versions"] == [] and body["enough_data"] is False and "synthetic" in body["note"]


def test_prediction_accuracy_matches_hand_computed_values(owner_engine, q):
    vid = add_version(owner_engine)
    add_prediction(owner_engine, q, vid, median=10, lower=5, upper=15, actual=12, naive=8)     # inside, err 2
    add_prediction(owner_engine, q, vid, median=20, lower=10, upper=30, actual=35, naive=25)   # outside, err 15
    with owner_engine.connect() as c:                         # an unfinished prediction must be ignored
        c.execute(text("insert into prediction_logs (clinic_id, model_version_id, pred_lower, pred_median, "
                       "pred_upper) values (:c, :m, 1, 2, 3)"), {"c": q.env.cid, "m": vid})
    body = api(q, "prediction-accuracy").json()
    (v,) = body["versions"]
    assert v["model_version"] == "lgbm-test-1" and v["n"] == 2
    assert v["mae_minutes"] == 8.5 and v["median_abs_error_minutes"] == 8.5
    assert v["bias_minutes"] == -8.5                           # mean(pred - actual) = (-2 + -15) / 2
    assert v["interval_coverage"] == 0.5
    assert v["naive_baseline_mae_minutes"] == 7.0              # mean(|8-12|, |25-35|) = (4 + 10) / 2
    assert body["enough_data"] is False                        # 2 < 30: flagged as anecdotal


def test_enough_data_flag_turns_on_at_thirty_completed_predictions(owner_engine, q):
    vid = add_version(owner_engine)
    for _ in range(30):
        add_prediction(owner_engine, q, vid, 10, 5, 15, 11, 9)
    assert api(q, "prediction-accuracy").json()["enough_data"] is True


def test_prediction_accuracy_is_per_clinic(owner_engine, q):
    vid = add_version(owner_engine)
    beta = setup_bookable(owner_engine, slug="beta")
    add_prediction(owner_engine, beta, vid, 10, 5, 15, 12, 8)
    assert api(q, "prediction-accuracy").json()["versions"] == []
    assert api(beta, "prediction-accuracy").json()["versions"][0]["n"] == 1
