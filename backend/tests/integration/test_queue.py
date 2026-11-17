"""Phase 5: walk-ins, appointment check-in, token allocation, state machine, call-next, isolation.

All data is synthetic. Appointments used for check-in are inserted directly for "today" (clinic
timezone is UTC in these tests) so nothing depends on the time of day the suite runs.
"""
from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import PASSWORD, login, new_client
from tests.integration.test_appointments import Bk, insert_appt, my_patient_id, setup_bookable
from tests.integration.test_clinic_management import mk_dept, mk_doctor, patch, post


@pytest.fixture
def q(owner_engine) -> Bk:
    return setup_bookable(owner_engine, slug="alpha", link_doctor=True)


def today_utc() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def mk_patient(b: Bk, name: str = "Walk In Synthetic") -> str:
    r = post(b.env.receptionist, f"{b.env.base}/patients", {"full_name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def walk_in(b: Bk, pid: str, client=None, doctor_id: str | None = None, **extra):
    c = client or b.env.receptionist
    return post(c, f"{b.env.base}/queue/walk-ins", {"doctor_id": doctor_id or b.doctor["id"], "patient_id": pid, **extra})


def act(b: Bk, token_id: str, action: str, client=None, body=None):
    return post(client or b.env.doctor, f"{b.env.base}/queue/tokens/{token_id}/{action}", body)


def board(b: Bk, client=None, doctor_id: str | None = None):
    c = client or b.env.doctor
    return c.get(f"{b.env.base}/doctors/{doctor_id or b.doctor['id']}/queue")


def check_in(b: Bk, appt_id: str, client=None):
    return post(client or b.env.receptionist, f"{b.env.base}/appointments/{appt_id}/check-in")


def extra_admin(b: Bk) -> object:
    c = new_client()
    assert login(c, "admin-alpha@example.com", PASSWORD).status_code == 200
    return c


# --------------------------------------------------------------------- tokens
def test_walk_in_gets_sequential_labels_and_positions(q):
    t = [walk_in(q, mk_patient(q, f"Patient {i}")).json() for i in range(3)]
    assert [x["token_label"] for x in t] == ["G-001", "G-002", "G-003"]
    assert [x["position"] for x in t] == [1, 2, 3]
    assert all(x["status"] == "WAITING" and x["source"] == "WALK_IN" for x in t)
    assert [w["token_label"] for w in board(q).json()["waiting"]] == ["G-001", "G-002", "G-003"]


def test_each_department_prefix_has_its_own_counter(q):
    other = mk_doctor(q.env, mk_dept(q.env, "Cardiology", "C"), "Dr Cardio")
    a = walk_in(q, mk_patient(q, "Pat A")).json()
    b = walk_in(q, mk_patient(q, "Pat B"), doctor_id=other["id"]).json()
    assert a["token_label"] == "G-001" and b["token_label"] == "C-001"


def test_duplicate_walk_in_blocked_until_token_ends(q):
    pid = mk_patient(q)
    first = walk_in(q, pid)
    assert first.status_code == 201
    assert walk_in(q, pid).status_code == 409
    assert act(q, first.json()["id"], "cancel", q.env.receptionist).status_code == 200
    assert walk_in(q, pid).status_code == 201                    # cancelled tokens are not "live"


def test_walk_in_validation_and_permissions(q):
    pid = mk_patient(q)
    assert walk_in(q, pid, priority=1).status_code == 422        # priority not enabled for this clinic
    assert walk_in(q, str(uuid.uuid4())).status_code == 404
    assert walk_in(q, pid, doctor_id=str(uuid.uuid4())).status_code == 404
    assert post(q.env.receptionist, f"{q.env.base}/queue/walk-ins",
                {"doctor_id": q.doctor["id"], "patient_id": pid, "extra": 1}).status_code == 422
    for c in (q.env.patient, q.env.doctor):
        assert walk_in(q, pid, client=c).status_code == 403
    assert post(q.env.admin, f"{q.env.base}/doctors/{q.doctor['id']}/status", {"status": "OFF_DUTY"}).status_code == 200
    assert walk_in(q, pid).status_code == 409


def test_priority_walk_in_jumps_the_line_when_enabled(q):
    assert patch(q.env.admin, q.env.base, {"settings": {"walkin_priority_enabled": True}}).status_code == 200
    normal = walk_in(q, mk_patient(q, "Normal")).json()
    urgent = walk_in(q, mk_patient(q, "Urgent"), priority=2).json()
    order = [w["id"] for w in board(q).json()["waiting"]]
    assert order == [urgent["id"], normal["id"]]


# ---------------------------------------------------------------- state machine
def test_full_consultation_flow_with_event_log(q, owner_engine):
    tok = walk_in(q, mk_patient(q)).json()
    assert act(q, tok["id"], "call").json()["status"] == "CALLED"
    assert act(q, tok["id"], "start").json()["status"] == "IN_CONSULTATION"
    done = act(q, tok["id"], "complete").json()
    assert done["status"] == "COMPLETED" and done["completed_at"] and done["version"] == 4
    events = q.env.admin.get(f"{q.env.base}/queue/tokens/{tok['id']}/events").json()
    assert [e["to_status"] for e in events] == ["WAITING", "CALLED", "IN_CONSULTATION", "COMPLETED"]
    assert events[0]["from_status"] is None and events[1]["from_status"] == "WAITING"
    with owner_engine.connect() as c:
        row = c.execute(text("select ended_at, duration_minutes, actual_wait_minutes from consultations "
                             "where token_id = :t"), {"t": tok["id"]}).one()
    assert row[0] is not None and row[1] is not None and row[2] is not None
    assert board(q).json()["finished_today"] == 1


@pytest.mark.parametrize("action", ["start", "complete", "requeue", "no-show"])
def test_illegal_transitions_from_waiting_rejected(q, action):
    tok = walk_in(q, mk_patient(q)).json()
    assert act(q, tok["id"], action).status_code == 409


def test_terminal_tokens_cannot_move(q):
    tok = walk_in(q, mk_patient(q)).json()
    for a in ("call", "start", "complete"):
        assert act(q, tok["id"], a).status_code == 200
    for a in ("call", "start", "complete", "skip", "requeue", "no-show", "cancel"):
        assert act(q, tok["id"], a, q.env.admin).status_code == 409, a


def test_unknown_action_is_rejected(q):
    tok = walk_in(q, mk_patient(q)).json()
    assert act(q, tok["id"], "explode").status_code == 422
    assert act(q, str(uuid.uuid4()), "call").status_code == 404


def test_only_one_patient_called_or_in_consultation_per_doctor(q):
    a = walk_in(q, mk_patient(q, "Patient A")).json()
    b = walk_in(q, mk_patient(q, "Patient B")).json()
    assert act(q, a["id"], "call").status_code == 200
    assert act(q, b["id"], "call").status_code == 409
    assert post(q.env.doctor, f"{q.env.base}/doctors/{q.doctor['id']}/queue/call-next").status_code == 409
    assert act(q, a["id"], "skip").status_code == 200            # frees the doctor
    assert act(q, b["id"], "call").status_code == 200


def test_skip_requeue_and_no_show_flow(q):
    a = walk_in(q, mk_patient(q, "Patient A")).json()
    assert act(q, a["id"], "call").status_code == 200
    assert act(q, a["id"], "skip", body={"reason": "Stepped out"}).json()["status"] == "SKIPPED"
    assert [s["id"] for s in board(q).json()["skipped"]] == [a["id"]]
    back = act(q, a["id"], "requeue").json()
    assert back["status"] == "WAITING" and back["called_at"] is None
    assert act(q, a["id"], "call").status_code == 200
    assert act(q, a["id"], "no-show").json()["status"] == "NO_SHOW"
    assert walk_in(q, a["patient_id"]).status_code == 201         # no-show frees the patient to rejoin
    events = q.env.admin.get(f"{q.env.base}/queue/tokens/{a['id']}/events").json()
    assert any(e["reason"] == "Stepped out" for e in events)


# ---------------------------------------------------------------- ordering policy
def test_appointment_first_policy_puts_booked_patient_ahead_of_earlier_walk_in(q, owner_engine):
    walker = walk_in(q, mk_patient(q, "Walker")).json()
    appt_pid = mk_patient(q, "Booked")
    appt = insert_appt(owner_engine, q, today_utc() + timedelta(hours=10), appt_pid)
    booked = check_in(q, appt).json()
    order = [w["id"] for w in board(q).json()["waiting"]]
    assert order == [booked["id"], walker["id"]]
    called = post(q.env.doctor, f"{q.env.base}/doctors/{q.doctor['id']}/queue/call-next").json()
    assert called["id"] == booked["id"] and called["status"] == "CALLED"


def test_fifo_policy_follows_arrival_order(q, owner_engine):
    assert patch(q.env.admin, q.env.base, {"settings": {"queue_policy": "FIFO"}}).status_code == 200
    walker = walk_in(q, mk_patient(q, "Walker")).json()
    appt = insert_appt(owner_engine, q, today_utc() + timedelta(hours=10), mk_patient(q, "Booked"))
    booked = check_in(q, appt).json()
    assert [w["id"] for w in board(q).json()["waiting"]] == [walker["id"], booked["id"]]
    assert board(q).json()["policy"] == "FIFO"


def test_booked_patients_are_ordered_by_appointment_time(q, owner_engine):
    late = insert_appt(owner_engine, q, today_utc() + timedelta(hours=11), mk_patient(q, "Late"))
    early = insert_appt(owner_engine, q, today_utc() + timedelta(hours=9), mk_patient(q, "Early"))
    t_late = check_in(q, late).json()            # arrives first but is booked later
    t_early = check_in(q, early).json()
    assert [w["id"] for w in board(q).json()["waiting"]] == [t_early["id"], t_late["id"]]


def test_call_next_with_empty_queue_is_409(q):
    assert post(q.env.doctor, f"{q.env.base}/doctors/{q.doctor['id']}/queue/call-next").status_code == 409


# -------------------------------------------------------------------- check-in
def test_check_in_creates_token_and_syncs_appointment(q, owner_engine):
    pid = mk_patient(q, "Booked Patient")
    appt = insert_appt(owner_engine, q, today_utc() + timedelta(hours=10), pid)
    tok = check_in(q, appt)
    assert tok.status_code == 201, tok.text
    t = tok.json()
    assert t["source"] == "APPOINTMENT" and t["appointment_id"] == appt and t["token_label"] == "G-001"
    assert q.env.admin.get(f"{q.env.base}/appointments/{appt}").json()["status"] == "CHECKED_IN"
    assert check_in(q, appt).status_code == 409                   # already checked in
    act(q, t["id"], "call")
    act(q, t["id"], "start")
    assert q.env.admin.get(f"{q.env.base}/appointments/{appt}").json()["status"] == "IN_PROGRESS"
    act(q, t["id"], "complete")
    assert q.env.admin.get(f"{q.env.base}/appointments/{appt}").json()["status"] == "COMPLETED"


def test_check_in_rules(q, owner_engine):
    pid = mk_patient(q)
    day = today_utc()
    pending = insert_appt(owner_engine, q, day + timedelta(hours=1), pid, status="PENDING")
    future = insert_appt(owner_engine, q, day + timedelta(days=2, hours=1), pid)
    cancelled = insert_appt(owner_engine, q, day + timedelta(hours=2), pid, status="CANCELLED")
    for appt in (pending, future, cancelled):
        assert check_in(q, appt).status_code == 409
    assert check_in(q, str(uuid.uuid4())).status_code == 404
    ok = insert_appt(owner_engine, q, day + timedelta(hours=3), pid)
    assert check_in(q, ok, q.env.patient).status_code == 403
    assert check_in(q, ok, q.env.doctor).status_code == 403
    assert check_in(q, ok, q.env.admin).status_code == 201


def test_cancelling_a_checked_in_token_cancels_the_appointment(q, owner_engine):
    appt = insert_appt(owner_engine, q, today_utc() + timedelta(hours=10), mk_patient(q))
    tok = check_in(q, appt).json()
    assert act(q, tok["id"], "cancel", q.env.receptionist, {"reason": "Left early"}).status_code == 200
    got = q.env.admin.get(f"{q.env.base}/appointments/{appt}").json()
    assert got["status"] == "CANCELLED" and got["cancel_reason"] == "Left early"


# ------------------------------------------------------- doctor / patient access
def test_doctor_sees_and_acts_on_own_queue_only(q):
    other = mk_doctor(q.env, mk_dept(q.env, "Other", "O"), "Dr Other")
    mine = walk_in(q, mk_patient(q, "Mine")).json()
    theirs = walk_in(q, mk_patient(q, "Theirs"), doctor_id=other["id"]).json()
    assert board(q).status_code == 200
    assert board(q, doctor_id=other["id"]).status_code == 404
    assert board(q, q.env.admin, other["id"]).status_code == 200
    assert act(q, theirs["id"], "call").status_code == 404
    assert q.env.doctor.get(f"{q.env.base}/queue/tokens/{theirs['id']}").status_code == 404
    assert q.env.doctor.get(f"{q.env.base}/queue/tokens/{theirs['id']}/events").status_code == 404
    assert post(q.env.doctor, f"{q.env.base}/doctors/{other['id']}/queue/call-next").status_code == 404
    assert act(q, mine["id"], "call").status_code == 200


def test_patient_view_is_limited_to_own_token(q):
    me = my_patient_id(q)                                         # the account holder's own patient row
    other_pid = mk_patient(q, "Someone Else")
    walk_in(q, other_pid)
    mine = walk_in(q, me).json()
    got = q.env.patient.get(f"{q.env.base}/queue/mine").json()
    assert len(got) == 1 and got[0]["id"] == mine["id"] and got[0]["people_ahead"] == 1
    assert "patient_name" not in got[0]
    # patients cannot use staff endpoints
    assert q.env.patient.get(f"{q.env.base}/queue/tokens/{mine['id']}").status_code == 403
    assert q.env.patient.get(f"{q.env.base}/doctors/{q.doctor['id']}/queue").status_code == 403
    assert act(q, mine["id"], "call", q.env.patient).status_code == 403
    assert post(q.env.patient, f"{q.env.base}/doctors/{q.doctor['id']}/queue/call-next").status_code == 403
    # staff have no "mine"
    assert q.env.receptionist.get(f"{q.env.base}/queue/mine").status_code == 403


def test_patient_can_leave_queue_only_while_waiting_and_only_their_own(q):
    me = my_patient_id(q)
    stranger = walk_in(q, mk_patient(q, "Stranger")).json()
    mine = walk_in(q, me).json()
    assert act(q, stranger["id"], "cancel", q.env.patient).status_code == 404   # not theirs: looks nonexistent
    left = act(q, mine["id"], "cancel", q.env.patient)
    assert left.status_code == 200 and left.json()["status"] == "CANCELLED"
    again = walk_in(q, me).json()
    act(q, again["id"], "call")
    assert act(q, again["id"], "cancel", q.env.patient).status_code == 409      # already called
    skipped = act(q, again["id"], "skip").json()
    assert skipped["status"] == "SKIPPED"
    assert act(q, again["id"], "cancel", q.env.patient).status_code == 409      # patients: waiting only


def test_people_ahead_counts_serving_patient(q):
    me = my_patient_id(q)
    first = walk_in(q, mk_patient(q, "First")).json()
    walk_in(q, me)
    assert q.env.patient.get(f"{q.env.base}/queue/mine").json()[0]["people_ahead"] == 1
    act(q, first["id"], "call")
    assert q.env.patient.get(f"{q.env.base}/queue/mine").json()[0]["people_ahead"] == 1   # being served still counts
    act(q, first["id"], "start")
    act(q, first["id"], "complete")
    assert q.env.patient.get(f"{q.env.base}/queue/mine").json()[0]["people_ahead"] == 0


# --------------------------------------------------------------- isolation/security
def test_cross_tenant_isolation(owner_engine):
    a = setup_bookable(owner_engine, slug="alpha", link_doctor=True)
    b = setup_bookable(owner_engine, slug="beta", link_doctor=True)
    tok = walk_in(a, mk_patient(a)).json()
    assert board(a, b.env.admin, a.doctor["id"]).status_code == 404          # not a member of alpha
    assert b.env.admin.get(f"{a.env.base}/queue/tokens/{tok['id']}").status_code == 404
    assert act(a, tok["id"], "cancel", b.env.admin).status_code == 404
    # alpha's token id and doctor id used inside beta's own clinic path
    assert b.env.admin.get(f"{b.env.base}/queue/tokens/{tok['id']}").status_code == 404
    assert act(b, tok["id"], "cancel", b.env.admin).status_code == 404
    assert walk_in(b, mk_patient(b), client=b.env.admin, doctor_id=a.doctor["id"]).status_code == 404
    assert walk_in(b, tok["patient_id"], client=b.env.admin).status_code == 404   # alpha's patient id
    assert act(a, tok["id"], "cancel", a.env.admin).status_code == 200            # still intact for alpha


def test_csrf_and_auth_required(q):
    pid = mk_patient(q)
    r = q.env.receptionist.post(f"{q.env.base}/queue/walk-ins", json={"doctor_id": q.doctor["id"], "patient_id": pid})
    assert r.status_code == 403
    anon = new_client()
    assert anon.get(f"{q.env.base}/doctors/{q.doctor['id']}/queue").status_code == 401
    assert anon.get(f"{q.env.base}/queue/mine").status_code == 401


def test_audit_trail_written(q, owner_engine):
    tok = walk_in(q, mk_patient(q)).json()
    act(q, tok["id"], "call")
    with owner_engine.connect() as c:
        actions = {r[0] for r in c.execute(text("select action from audit_logs where action like 'queue.%'"))}
    assert {"queue.walk_in", "queue.call"} <= actions


def test_database_blocks_two_active_patients_even_if_service_is_bypassed(q, owner_engine):
    a = walk_in(q, mk_patient(q, "Patient A")).json()
    b = walk_in(q, mk_patient(q, "Patient B")).json()
    with owner_engine.begin() as c:
        c.execute(text("update queue_tokens set status='CALLED' where id=:i"), {"i": a["id"]})
    with pytest.raises(Exception) as err, owner_engine.begin() as c:
        c.execute(text("update queue_tokens set status='CALLED' where id=:i"), {"i": b["id"]})
    assert "uq_queue_tokens_one_active_per_doctor" in str(err.value)


# ------------------------------------------------------------------ concurrency
def test_concurrent_walk_ins_get_unique_gapless_tokens(q):
    n = 8
    pids = [mk_patient(q, f"Racer {i}") for i in range(n)]
    clients = [extra_admin(q) for _ in range(n)]
    barrier = threading.Barrier(n)
    results: list[tuple[int, str | None]] = []

    def go(c, pid):
        barrier.wait()
        r = walk_in(q, pid, client=c)
        results.append((r.status_code, r.json().get("token_label")))

    threads = [threading.Thread(target=go, args=(c, p)) for c, p in zip(clients, pids, strict=True)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(code == 201 for code, _ in results), results
    assert sorted(label for _, label in results) == [f"G-{i:03d}" for i in range(1, n + 1)]


def test_concurrent_call_next_calls_exactly_one_patient(q, owner_engine):
    for i in range(4):
        walk_in(q, mk_patient(q, f"Waiting {i}"))
    n = 6
    clients = [extra_admin(q) for _ in range(n)]
    barrier = threading.Barrier(n)
    codes: list[int] = []

    def go(c):
        barrier.wait()
        codes.append(post(c, f"{q.env.base}/doctors/{q.doctor['id']}/queue/call-next").status_code)

    threads = [threading.Thread(target=go, args=(c,)) for c in clients]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200] + [409] * (n - 1), codes
    with owner_engine.connect() as c:
        assert c.execute(text("select count(*) from queue_tokens where status='CALLED'")).scalar() == 1
