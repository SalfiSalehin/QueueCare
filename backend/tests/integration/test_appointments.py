"""Phase 4: slots, booking, double-booking prevention, cancel/reschedule, patients, isolation.

All times come from the slots API or are inserted relative to "now", so these tests do not depend on
the date they run. All data is synthetic.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import csrf, new_client, signup
from tests.integration.test_clinic_management import Env, mk_dept, mk_doctor, patch, post, setup_clinic


@dataclass
class Bk:
    env: Env
    doctor: dict
    doctor_user_id: str


def _open_all_week(env: Env, doctor_id: str) -> None:
    for dow in range(7):
        r = post(env.admin, f"{env.base}/doctors/{doctor_id}/schedules",
                 {"day_of_week": dow, "start_time": "09:00:00", "end_time": "12:00:00"})
        assert r.status_code == 201, r.text


def setup_bookable(owner_engine, slug="alpha", link_doctor=False, **doc_extra) -> Bk:
    env = setup_clinic(owner_engine, slug)
    dept = mk_dept(env)
    uid = ""
    extra = dict(doc_extra)
    if link_doctor:
        with owner_engine.connect() as c:
            uid = str(c.execute(text("select id from users where email=:e"), {"e": env.emails["DOCTOR"]}).scalar())
        extra["user_id"] = uid
    doc = mk_doctor(env, dept, "Dr Bookable", default_slot_minutes=30, buffer_minutes=0, **extra)
    _open_all_week(env, doc["id"])
    # Cutoff 0 keeps tests independent of the time of day; cutoff tests set it explicitly.
    assert patch(env.admin, env.base, {"settings": {"cancellation_cutoff_hours": 0}}).status_code == 200
    return Bk(env, doc, uid)


@pytest.fixture
def bk(owner_engine) -> Bk:
    return setup_bookable(owner_engine)


def slots(bk: Bk, client=None) -> list[dict]:
    c = client or bk.env.patient
    r = c.get(f"{bk.env.base}/doctors/{bk.doctor['id']}/slots")
    assert r.status_code == 200, r.text
    return r.json()


def book(bk: Bk, starts_at: str, client=None, **extra):
    c = client or bk.env.patient
    return post(c, f"{bk.env.base}/appointments", {"doctor_id": bk.doctor["id"], "starts_at": starts_at, **extra})


def insert_appt(owner_engine, bk: Bk, starts_at: datetime, patient_id: str, status="CONFIRMED", minutes=30) -> str:
    aid = str(uuid.uuid4())
    with owner_engine.connect() as c:
        c.execute(text(
            "insert into appointments (id, clinic_id, doctor_id, patient_id, starts_at, ends_at, status) "
            "values (:i, :c, :d, :p, :s, :e, :st)"),
            {"i": aid, "c": bk.env.cid, "d": bk.doctor["id"], "p": patient_id, "s": starts_at,
             "e": starts_at + timedelta(minutes=minutes), "st": status})
    return aid


def my_patient_id(bk: Bk, client=None) -> str:
    c = client or bk.env.patient
    first = slots(bk, c)[0]["starts_at"]
    r = book(bk, first, c)
    assert r.status_code == 201, r.text
    pid = r.json()["patient_id"]
    assert post(c, f"{bk.env.base}/appointments/{r.json()['id']}/cancel").status_code == 200
    return pid


# ------------------------------------------------------------------------ slots
def test_slots_listing_is_sorted_future_and_on_grid(bk):
    s = slots(bk)
    assert len(s) > 0
    starts = [x["starts_at"] for x in s]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    now = datetime.now(UTC)
    for x in s:
        t = datetime.fromisoformat(x["starts_at"])
        assert t >= now + timedelta(minutes=59)           # min-notice default is 60 minutes
        assert t.minute in (0, 30) and t.second == 0
        assert x["starts_at_local"]


def test_slots_range_validation(bk):
    base = f"{bk.env.base}/doctors/{bk.doctor['id']}/slots"
    assert bk.env.patient.get(base, params={"from": "2030-01-10", "to": "2030-01-01"}).status_code == 422
    assert bk.env.patient.get(base, params={"from": "2030-01-01", "to": "2030-03-01"}).status_code == 422
    assert bk.env.patient.get(base, params={"from": "not-a-date"}).status_code == 422


def test_slots_unknown_or_inactive_doctor_404(bk):
    assert bk.env.patient.get(f"{bk.env.base}/doctors/{uuid.uuid4()}/slots").status_code == 404
    assert patch(bk.env.admin, f"{bk.env.base}/doctors/{bk.doctor['id']}", {"is_active": False}).status_code == 200
    assert bk.env.patient.get(f"{bk.env.base}/doctors/{bk.doctor['id']}/slots").status_code == 404


def test_off_duty_doctor_has_no_slots_and_blocks_booking(bk):
    first = slots(bk)[0]["starts_at"]
    assert post(bk.env.admin, f"{bk.env.base}/doctors/{bk.doctor['id']}/status", {"status": "OFF_DUTY"}).status_code == 200
    assert slots(bk) == []
    assert book(bk, first).status_code == 409


def test_time_off_removes_slots(bk):
    s = slots(bk)
    start = datetime.fromisoformat(s[0]["starts_at"])
    r = post(bk.env.admin, f"{bk.env.base}/doctors/{bk.doctor['id']}/time-off",
             {"starts_at": (start - timedelta(minutes=1)).isoformat(), "ends_at": (start + timedelta(minutes=31)).isoformat()})
    assert r.status_code == 201, r.text
    assert s[0]["starts_at"] not in [x["starts_at"] for x in slots(bk)]
    assert book(bk, s[0]["starts_at"]).status_code == 409


# ---------------------------------------------------------------------- booking
def test_patient_books_and_sees_own_appointment(bk):
    s = slots(bk)[0]
    r = book(bk, s["starts_at"])
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "CONFIRMED" and a["doctor_name"] == "Dr Bookable" and a["patient_name"]
    assert a["starts_at"] == s["starts_at"]
    assert s["starts_at"] not in [x["starts_at"] for x in slots(bk)]
    listing = bk.env.patient.get(f"{bk.env.base}/appointments").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == a["id"]
    assert bk.env.patient.get(f"{bk.env.base}/appointments/{a['id']}").status_code == 200


def test_booking_validation(bk):
    first = slots(bk)[0]["starts_at"]
    t = datetime.fromisoformat(first)
    assert book(bk, t.replace(tzinfo=None).isoformat()).status_code == 422                        # naive timestamp
    assert book(bk, (t + timedelta(minutes=7)).isoformat()).status_code == 422             # off the grid
    assert book(bk, (datetime.now(UTC) - timedelta(days=1)).isoformat()).status_code == 422  # past
    assert book(bk, (datetime.now(UTC) + timedelta(days=400)).isoformat()).status_code == 422  # beyond horizon
    assert book(bk, first, patient_id=str(uuid.uuid4())).status_code == 422                # patients can't pick patient
    assert post(bk.env.patient, f"{bk.env.base}/appointments",
                {"doctor_id": bk.doctor["id"], "starts_at": first, "ends_at": first}).status_code == 422  # extra field
    assert post(bk.env.patient, f"{bk.env.base}/appointments",
                {"doctor_id": str(uuid.uuid4()), "starts_at": first}).status_code == 404


def test_double_booking_returns_409_and_keeps_first(bk):
    first = slots(bk)[0]["starts_at"]
    assert book(bk, first).status_code == 201
    other = new_client()
    signup(other, "patient2-alpha@example.com")
    assert other.post(f"{bk.env.base}/join", headers=csrf(other)).status_code == 204
    assert book(bk, first, other).status_code == 409
    n = bk.env.admin.get(f"{bk.env.base}/appointments", params={"status": "CONFIRMED"}).json()["total"]
    assert n == 1


def test_overlap_with_buffer_is_blocked(owner_engine):
    b = setup_bookable(owner_engine, slug="buf")
    # a 30-minute slot with a 15-minute buffer occupies 45 minutes; the next grid slot then starts at +45
    assert patch(b.env.admin, f"{b.env.base}/doctors/{b.doctor['id']}", {"buffer_minutes": 15}).status_code == 200
    s = slots(b)
    first = datetime.fromisoformat(s[0]["starts_at"])
    assert book(b, s[0]["starts_at"]).status_code == 201
    starts = {datetime.fromisoformat(x["starts_at"]) for x in slots(b)}
    assert first + timedelta(minutes=30) not in starts and first + timedelta(minutes=15) not in starts


def test_concurrent_booking_exactly_one_winner(bk):
    first = slots(bk)[0]["starts_at"]
    clients = []
    for i in range(6):
        c = new_client()
        signup(c, f"racer{i}-alpha@example.com")
        assert c.post(f"{bk.env.base}/join", headers=csrf(c)).status_code == 204
        clients.append(c)
    barrier = threading.Barrier(len(clients))
    codes: list[int] = []

    def go(c):
        barrier.wait()
        codes.append(book(bk, first, c).status_code)

    threads = [threading.Thread(target=go, args=(c,)) for c in clients]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [201] + [409] * 5, codes


def test_patient_cap_on_upcoming_appointments(bk):
    s = [x["starts_at"] for x in slots(bk)[:8]]
    for ts in s[:5]:
        assert book(bk, ts).status_code == 201
    r = book(bk, s[5])
    assert r.status_code == 409 and "at most" in r.json()["error"]["message"]


# ---------------------------------------------------------------- staff booking
def test_staff_books_for_registered_walkin_patient(bk):
    r = post(bk.env.receptionist, f"{bk.env.base}/patients", {"full_name": "Walk In Synthetic", "phone": "+880 1700-000000"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    first = slots(bk)[0]["starts_at"]
    assert book(bk, first, bk.env.receptionist).status_code == 422                        # patient_id required
    ok = book(bk, first, bk.env.receptionist, patient_id=pid)
    assert ok.status_code == 201 and ok.json()["patient_name"] == "Walk In Synthetic"
    assert book(bk, slots(bk)[0]["starts_at"], bk.env.receptionist, patient_id=str(uuid.uuid4())).status_code == 404


def test_patients_endpoints_are_front_desk_only(bk):
    assert post(bk.env.admin, f"{bk.env.base}/patients", {"full_name": "Jane Synthetic"}).status_code == 201
    for c in (bk.env.patient, bk.env.doctor):
        assert c.get(f"{bk.env.base}/patients").status_code == 403
        assert post(c, f"{bk.env.base}/patients", {"full_name": "Nope Nope"}).status_code == 403
    found = bk.env.receptionist.get(f"{bk.env.base}/patients", params={"q": "jane"}).json()
    assert found["total"] == 1
    assert bk.env.receptionist.get(f"{bk.env.base}/patients", params={"q": "%%"}).json()["total"] == 0  # wildcard escaped
    assert post(bk.env.admin, f"{bk.env.base}/patients", {"full_name": "X", "phone": "abc"}).status_code == 422


def test_doctor_sees_only_own_appointments(owner_engine):
    b = setup_bookable(owner_engine, slug="dr", link_doctor=True)
    # a second doctor in the same clinic with a different schedule
    other = mk_doctor(b.env, mk_dept(b.env, "Other", "O"), "Dr Other", default_slot_minutes=30, buffer_minutes=0)
    _open_all_week(b.env, other["id"])
    mine = slots(b)[0]["starts_at"]
    assert book(b, mine).status_code == 201
    r = post(b.env.patient, f"{b.env.base}/appointments", {"doctor_id": other["id"], "starts_at": mine})
    assert r.status_code == 201
    seen = b.env.doctor.get(f"{b.env.base}/appointments").json()
    assert seen["total"] == 1 and seen["items"][0]["doctor_id"] == b.doctor["id"]
    assert b.env.admin.get(f"{b.env.base}/appointments").json()["total"] == 2
    assert b.env.doctor.get(f"{b.env.base}/appointments/{r.json()['id']}").status_code == 404


def test_other_patient_cannot_see_or_touch_appointment(bk):
    a = book(bk, slots(bk)[0]["starts_at"]).json()
    other = new_client()
    signup(other, "patient2-alpha@example.com")
    assert other.post(f"{bk.env.base}/join", headers=csrf(other)).status_code == 204
    assert other.get(f"{bk.env.base}/appointments").json()["total"] == 0
    assert other.get(f"{bk.env.base}/appointments/{a['id']}").status_code == 404
    assert post(other, f"{bk.env.base}/appointments/{a['id']}/cancel").status_code == 404
    later = slots(bk)[3]["starts_at"]
    assert post(other, f"{bk.env.base}/appointments/{a['id']}/reschedule", {"starts_at": later}).status_code == 404


# ------------------------------------------------------------- cancel / reschedule
def test_patient_cancel_frees_slot_and_is_final(bk):
    first = slots(bk)[0]["starts_at"]
    a = book(bk, first).json()
    r = post(bk.env.patient, f"{bk.env.base}/appointments/{a['id']}/cancel", {"reason": "Changed my mind"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED" and r.json()["cancel_reason"] == "Changed my mind"
    assert first in [x["starts_at"] for x in slots(bk)]
    assert post(bk.env.patient, f"{bk.env.base}/appointments/{a['id']}/cancel").status_code == 409  # already cancelled
    assert book(bk, first).status_code == 201                                                       # slot reusable


def test_cancel_cutoff_applies_to_patients_not_staff(bk, owner_engine):
    pid = my_patient_id(bk)
    assert patch(bk.env.admin, bk.env.base, {"settings": {"cancellation_cutoff_hours": 2}}).status_code == 200
    soon = insert_appt(owner_engine, bk, datetime.now(UTC) + timedelta(minutes=30), pid)
    r = post(bk.env.patient, f"{bk.env.base}/appointments/{soon}/cancel")
    assert r.status_code == 409
    assert post(bk.env.patient, f"{bk.env.base}/appointments/{soon}/reschedule",
                {"starts_at": slots(bk)[2]["starts_at"]}).status_code == 409
    assert post(bk.env.receptionist, f"{bk.env.base}/appointments/{soon}/cancel", {"reason": "Phone call"}).status_code == 200


def test_cutoff_setting_is_respected(bk, owner_engine):
    pid = my_patient_id(bk)
    assert patch(bk.env.admin, bk.env.base, {"settings": {"cancellation_cutoff_hours": 2}}).status_code == 200
    soon = insert_appt(owner_engine, bk, datetime.now(UTC) + timedelta(minutes=30), pid)
    assert post(bk.env.patient, f"{bk.env.base}/appointments/{soon}/cancel").status_code == 409
    assert patch(bk.env.admin, bk.env.base, {"settings": {"cancellation_cutoff_hours": 0}}).status_code == 200
    assert post(bk.env.patient, f"{bk.env.base}/appointments/{soon}/cancel").status_code == 200


def test_reschedule_moves_appointment_atomically(bk):
    s = [x["starts_at"] for x in slots(bk)]
    a = book(bk, s[0]).json()
    r = post(bk.env.patient, f"{bk.env.base}/appointments/{a['id']}/reschedule", {"starts_at": s[4]})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["id"] != a["id"] and new["starts_at"] == s[4] and new["rescheduled_from"] == a["id"]
    assert new["status"] == "CONFIRMED"
    old = bk.env.patient.get(f"{bk.env.base}/appointments/{a['id']}").json()
    assert old["status"] == "CANCELLED" and old["cancel_reason"] == "Rescheduled"
    free = [x["starts_at"] for x in slots(bk)]
    assert s[0] in free and s[4] not in free


def test_reschedule_conflict_leaves_original_untouched(bk):
    s = [x["starts_at"] for x in slots(bk)]
    other = new_client()
    signup(other, "patient2-alpha@example.com")
    assert other.post(f"{bk.env.base}/join", headers=csrf(other)).status_code == 204
    assert book(bk, s[4], other).status_code == 201
    a = book(bk, s[0]).json()
    r = post(bk.env.patient, f"{bk.env.base}/appointments/{a['id']}/reschedule", {"starts_at": s[4]})
    assert r.status_code == 409
    still = bk.env.patient.get(f"{bk.env.base}/appointments/{a['id']}").json()
    assert still["status"] == "CONFIRMED" and still["starts_at"] == s[0]
    assert bk.env.patient.get(f"{bk.env.base}/appointments").json()["total"] == 1


def test_reschedule_into_overlapping_own_range_and_noop(owner_engine):
    b = setup_bookable(owner_engine, slug="shift")
    s = [x["starts_at"] for x in slots(b)]
    a = book(b, s[0]).json()
    same = post(b.env.patient, f"{b.env.base}/appointments/{a['id']}/reschedule", {"starts_at": s[0]})
    assert same.status_code == 422                                            # already there
    moved = post(b.env.patient, f"{b.env.base}/appointments/{a['id']}/reschedule", {"starts_at": s[1]})
    assert moved.status_code == 200 and moved.json()["starts_at"] == s[1]     # own old slot never blocks itself


def test_reschedule_to_other_doctor(bk):
    other = mk_doctor(bk.env, mk_dept(bk.env, "Other", "O"), "Dr Other", default_slot_minutes=30, buffer_minutes=0)
    _open_all_week(bk.env, other["id"])
    s = slots(bk)[0]["starts_at"]
    a = book(bk, s).json()
    r = post(bk.env.patient, f"{bk.env.base}/appointments/{a['id']}/reschedule", {"starts_at": s, "doctor_id": other["id"]})
    assert r.status_code == 200 and r.json()["doctor_id"] == other["id"]


def test_confirm_pending_only_by_front_desk(bk, owner_engine):
    pid = my_patient_id(bk)
    pending = insert_appt(owner_engine, bk, datetime.now(UTC) + timedelta(days=3), pid, status="PENDING")
    assert post(bk.env.patient, f"{bk.env.base}/appointments/{pending}/confirm").status_code == 403
    assert post(bk.env.doctor, f"{bk.env.base}/appointments/{pending}/confirm").status_code == 403
    ok = post(bk.env.receptionist, f"{bk.env.base}/appointments/{pending}/confirm")
    assert ok.status_code == 200 and ok.json()["status"] == "CONFIRMED"
    assert post(bk.env.receptionist, f"{bk.env.base}/appointments/{pending}/confirm").status_code == 409


def test_non_movable_statuses_rejected(bk, owner_engine):
    pid = my_patient_id(bk)
    far = datetime.now(UTC) + timedelta(days=3)
    for i, st in enumerate(("IN_PROGRESS", "COMPLETED", "NO_SHOW")):
        aid = insert_appt(owner_engine, bk, far + timedelta(hours=i), pid, status=st)
        assert post(bk.env.receptionist, f"{bk.env.base}/appointments/{aid}/cancel").status_code == 409
        assert post(bk.env.receptionist, f"{bk.env.base}/appointments/{aid}/reschedule",
                    {"starts_at": slots(bk)[0]["starts_at"]}).status_code == 409


# ------------------------------------------------------- list filters / security
def test_list_filters(bk):
    s = [x["starts_at"] for x in slots(bk)]
    a = book(bk, s[0]).json()
    book(bk, s[1])
    post(bk.env.patient, f"{bk.env.base}/appointments/{a['id']}/cancel")
    base = f"{bk.env.base}/appointments"
    assert bk.env.admin.get(base, params={"status": "CANCELLED"}).json()["total"] == 1
    assert bk.env.admin.get(base, params={"status": "BOGUS"}).status_code == 422
    assert bk.env.admin.get(base, params={"doctor_id": str(uuid.uuid4())}).json()["total"] == 0
    local_day = datetime.fromisoformat(a["starts_at_local"]).date().isoformat()
    assert bk.env.admin.get(base, params={"date": local_day}).json()["total"] >= 1
    assert len(bk.env.admin.get(base, params={"limit": 1}).json()["items"]) == 1
    assert bk.env.admin.get(base, params={"limit": 1000}).status_code == 422


def test_cross_tenant_isolation(owner_engine):
    a = setup_bookable(owner_engine, slug="alpha")
    b = setup_bookable(owner_engine, slug="beta")
    appt = book(a, slots(a)[0]["starts_at"]).json()
    # beta's admin is not a member of alpha: 404 everywhere, never 403/200
    assert b.env.admin.get(f"{a.env.base}/appointments/{appt['id']}").status_code == 404
    assert b.env.admin.get(f"{a.env.base}/appointments").status_code == 404
    assert post(b.env.admin, f"{a.env.base}/appointments/{appt['id']}/cancel").status_code == 404
    assert b.env.admin.get(f"{a.env.base}/doctors/{a.doctor['id']}/slots").status_code == 404
    # using alpha's doctor id inside beta's own clinic must not work either
    r = post(b.env.patient, f"{b.env.base}/appointments",
             {"doctor_id": a.doctor["id"], "starts_at": slots(b)[0]["starts_at"]})
    assert r.status_code == 404
    assert b.env.admin.get(f"{b.env.base}/appointments/{appt['id']}").status_code == 404


def test_csrf_and_auth_required(bk):
    first = slots(bk)[0]["starts_at"]
    r = bk.env.patient.post(f"{bk.env.base}/appointments", json={"doctor_id": bk.doctor["id"], "starts_at": first})
    assert r.status_code == 403                                                    # cookie session without CSRF header
    anon = new_client()
    assert anon.get(f"{bk.env.base}/appointments").status_code == 401
    assert anon.get(f"{bk.env.base}/doctors/{bk.doctor['id']}/slots").status_code == 401


def test_audit_trail_written(bk, owner_engine):
    s = [x["starts_at"] for x in slots(bk)]
    a = book(bk, s[0]).json()
    post(bk.env.patient, f"{bk.env.base}/appointments/{a['id']}/reschedule", {"starts_at": s[3]})
    with owner_engine.connect() as c:
        actions = {r[0] for r in c.execute(text("select action from audit_logs where action like 'appointment.%'"))}
    assert {"appointment.booked", "appointment.rescheduled"} <= actions
