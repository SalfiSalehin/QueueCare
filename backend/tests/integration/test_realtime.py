"""Phase 6: WebSocket tickets, gateway authorization, scoped delivery, outbox no-loss guarantees.

The relay is driven explicitly (OUTBOX_RELAY_ENABLED=false in the test environment), so there is no
timing guesswork about when events are published. Messages are read with a ping/pong "barrier" and
bounded retries, so a bug makes a test fail instead of hanging.
"""
from __future__ import annotations

import contextlib
import json
import time
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import func, select, text
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.database import get_sessionmaker, set_rls_context
from app.models import OutboxEvent
from app.websocket.broker import get_broker
from app.websocket.tickets import issue_ticket
from app.workers.outbox_relay import RelayPublishError, relay_batch
from tests.conftest import csrf, new_client, signup
from tests.integration.test_appointments import Bk, book, my_patient_id, setup_bookable, slots
from tests.integration.test_clinic_management import post
from tests.integration.test_queue import act, mk_patient, walk_in


@pytest.fixture
def q(owner_engine) -> Bk:
    return setup_bookable(owner_engine, slug="alpha", link_doctor=True)


# ----------------------------------------------------------------------- helpers
def relay_all() -> int:
    total = 0
    while True:
        n = relay_batch(get_sessionmaker(), get_broker(None).publish_sync, 500)
        total += n
        if n == 0:
            return total


def ticket_for(client, b: Bk) -> str:
    r = post(client, f"{b.env.base}/realtime/ticket")
    assert r.status_code == 200, r.text
    return r.json()["ticket"]


def ws_path(ticket: str) -> str:
    return f"/api/v1/ws?ticket={ticket}"


@contextmanager
def connect(client, path: str, **kw):
    """`client.websocket_connect`, but wait for the server to finish before the session is torn down.

    Starlette's test client sends the "disconnect" message and immediately cancels the server task
    without waiting for it. If the server is still cleaning up, that cancellation can escape and fail
    the test at random. Here the disconnect is sent first and we wait (bounded) until the server has
    unregistered this connection, so teardown only ever cancels a task that has already finished.
    """
    hub = client.app.state.hub
    with client.websocket_connect(path, **kw) as ws:
        before = hub.connection_count                      # includes this connection
        try:
            yield ws
        finally:
            with contextlib.suppress(Exception):
                ws.close(1000)
            deadline = time.monotonic() + 3.0
            while hub.connection_count >= before and time.monotonic() < deadline:
                time.sleep(0.01)


@contextmanager
def open_ws(client, b: Bk, **kw):
    with connect(client, ws_path(ticket_for(client, b)), **kw) as ws:
        assert ws.receive_json() == {"type": "ready"}
        yield ws


def barrier(ws) -> list[dict]:
    """Everything the server has queued for us up to a pong."""
    ws.send_json({"type": "ping"})
    out: list[dict] = []
    while True:
        msg = ws.receive_json()
        if msg == {"type": "pong"}:
            return out
        out.append(msg)


def events(ws, n: int, timeout: float = 5.0) -> list[dict]:
    """Wait (bounded) for at least n events, then briefly collect stragglers."""
    got: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(got) < n:
        got += barrier(ws)
        if len(got) < n:
            assert time.monotonic() < deadline, f"expected {n} event(s), got {got}"
            time.sleep(0.02)
    time.sleep(0.1)
    return got + barrier(ws)


def silent(ws) -> None:
    time.sleep(0.25)
    assert barrier(ws) == [] and barrier(ws) == []


def rejected(path: str, client, **kw) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(path, **kw):
        pass


def second_patient(b: Bk):
    c = new_client()
    signup(c, "patient2-alpha@example.com")
    assert c.post(f"{b.env.base}/join", headers=csrf(c)).status_code == 204
    return c


def kinds(msgs: list[dict]) -> list[str]:
    return [m["event"] for m in msgs]


# ------------------------------------------------------------------------ tickets
def test_any_member_can_mint_a_ticket_but_outsiders_and_anonymous_cannot(owner_engine, q):
    for c in (q.env.admin, q.env.receptionist, q.env.doctor, q.env.patient):
        r = post(c, f"{q.env.base}/realtime/ticket")
        assert r.status_code == 200
        body = r.json()
        assert body["expires_in"] == 30 and body["websocket_path"] == "/api/v1/ws" and len(body["ticket"]) > 50
    other = setup_bookable(owner_engine, slug="beta")
    assert post(other.env.admin, f"{q.env.base}/realtime/ticket").status_code == 404   # not a member of alpha
    assert new_client().post(f"{q.env.base}/realtime/ticket").status_code in (401, 403)
    no_csrf = q.env.patient.post(f"{q.env.base}/realtime/ticket")
    assert no_csrf.status_code == 403


# ------------------------------------------------------------- handshake rejection
def test_connection_without_valid_ticket_is_refused(q):
    c = q.env.patient
    rejected("/api/v1/ws", c)
    rejected("/api/v1/ws?ticket=", c)
    rejected("/api/v1/ws?ticket=garbage", c)
    access_token = c.cookies.get("qc_access")
    rejected(ws_path(access_token), c)                         # an access token is not a ticket


def test_expired_ticket_is_refused(q, owner_engine):
    s = get_settings()
    with owner_engine.connect() as conn:
        uid, sid = conn.execute(text("select u.id, s.id from users u join sessions s on s.user_id = u.id "
                                     "where u.email = 'patient-alpha@example.com'")).one()
    old = issue_ticket(s.jwt_secret, s.jwt_algorithm, user_id=uid, clinic_id=uuid.UUID(q.env.cid),
                       session_id=sid, ttl_seconds=30, now=time.time() - 300)
    rejected(ws_path(old), q.env.patient)
    fresh = issue_ticket(s.jwt_secret, s.jwt_algorithm, user_id=uid, clinic_id=uuid.UUID(q.env.cid),
                         session_id=sid, ttl_seconds=30)
    with connect(q.env.patient, ws_path(fresh)) as ws:       # same ticket, just not expired
        assert ws.receive_json() == {"type": "ready"}


def test_ticket_can_only_be_used_once(q):
    t = ticket_for(q.env.patient, q)
    with connect(q.env.patient, ws_path(t)) as ws:
        assert ws.receive_json() == {"type": "ready"}
    rejected(ws_path(t), q.env.patient)                          # replay refused


def test_validly_signed_ticket_for_unknown_session_or_user_is_refused(q):
    s = get_settings()
    forged = issue_ticket(s.jwt_secret, s.jwt_algorithm, user_id=uuid.uuid4(), clinic_id=uuid.UUID(q.env.cid),
                          session_id=uuid.uuid4(), ttl_seconds=30)
    rejected(ws_path(forged), q.env.patient)


def test_ticket_stops_working_after_logout_style_session_revocation(q, owner_engine):
    t = ticket_for(q.env.patient, q)
    with owner_engine.begin() as conn:
        conn.execute(text("update sessions set revoked_at = now()"))
    rejected(ws_path(t), q.env.patient)


def test_ticket_stops_working_after_membership_removed(q, owner_engine):
    t = ticket_for(q.env.patient, q)
    with owner_engine.begin() as conn:
        conn.execute(text("update clinic_memberships set is_active = false where role = 'PATIENT'"))
    rejected(ws_path(t), q.env.patient)


def test_untrusted_origin_is_refused_but_trusted_or_missing_origin_is_allowed(q):
    c = q.env.patient
    rejected(ws_path(ticket_for(c, q)), c, headers={"origin": "https://evil.example"})
    with connect(c, ws_path(ticket_for(c, q)), headers={"origin": "http://localhost:3000"}) as ws:
        assert ws.receive_json() == {"type": "ready"}


# ------------------------------------------------------------------ client protocol
def test_ping_pong_and_strict_client_messages(q):
    with open_ws(q.env.patient, q) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    for bad in ({"type": "subscribe", "channel": f"clinic:{q.env.cid}:staff"}, {"type": "ping", "x": 1},
                {"hello": "world"}, [1, 2], "ping"):
        with open_ws(q.env.patient, q) as ws:
            ws.send_text(json.dumps(bad))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    with open_ws(q.env.patient, q) as ws:
        ws.send_text("{not json")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    with open_ws(q.env.patient, q) as ws:
        ws.send_text("x" * 5000)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_per_user_connection_cap(q):
    cap = get_settings().ws_max_connections_per_user
    with contextlib.ExitStack() as stack:
        for _ in range(cap):
            ws = stack.enter_context(connect(q.env.patient, ws_path(ticket_for(q.env.patient, q))))
            assert ws.receive_json() == {"type": "ready"}
        rejected(ws_path(ticket_for(q.env.patient, q)), q.env.patient)
    with open_ws(q.env.patient, q):                             # slots free again after they close
        pass


# ------------------------------------------------------------------ scoped delivery
def test_queue_events_reach_only_the_right_audiences(owner_engine, q):
    me = my_patient_id(q)
    stranger_client = second_patient(q)
    beta = setup_bookable(owner_engine, slug="beta", link_doctor=True)
    relay_all()                                                  # flush setup events to nobody

    with open_ws(q.env.receptionist, q) as staff, open_ws(q.env.doctor, q) as doctor, \
            open_ws(q.env.patient, q) as mine, open_ws(stranger_client, q) as other, \
            open_ws(beta.env.admin, beta) as foreign:
        tok = walk_in(q, me).json()
        assert relay_all() > 0

        staff_msgs, doctor_msgs = events(staff, 1), events(doctor, 1)
        assert kinds(staff_msgs) == kinds(doctor_msgs) == ["queue.updated"]
        for m in staff_msgs + doctor_msgs:
            assert m["type"] == "event" and m["id"] and m["version"] > 0 and m["ts"]
            assert m["data"] == {"doctor_id": q.doctor["id"], "token_id": tok["id"], "token_label": "G-001",
                                 "status": "WAITING", "token_version": 1, "change": "walk_in"}

        own = events(mine, 1)
        assert kinds(own) == ["queue.position"]
        assert own[0]["data"] == {"token_id": tok["id"], "token_label": "G-001", "doctor_id": q.doctor["id"],
                                  "status": "WAITING", "people_ahead": 0, "token_version": 1}

        silent(other)                                            # another patient: nothing
        silent(foreign)                                          # another clinic: nothing


def test_events_never_contain_patient_names(q):
    me = my_patient_id(q)
    stranger = walk_in(q, mk_patient(q, "Zelda Unmistakable")).json()
    relay_all()
    with open_ws(q.env.receptionist, q) as staff, open_ws(q.env.patient, q) as mine:
        tok = walk_in(q, me).json()
        act(q, stranger["id"], "call")
        relay_all()
        raw = json.dumps(events(staff, 2) + events(mine, 2))
        assert "Zelda" not in raw and "Unmistakable" not in raw and "Synthetic User" not in raw
        assert "patient_name" not in raw and "full_name" not in raw and tok["id"] in raw


def test_patient_position_updates_follow_the_queue(q):
    me = my_patient_id(q)
    first = walk_in(q, mk_patient(q, "Someone First")).json()
    relay_all()
    with open_ws(q.env.patient, q) as mine:
        walk_in(q, me)
        relay_all()
        assert [m["data"]["people_ahead"] for m in events(mine, 1)] == [1]
        act(q, first["id"], "call")
        relay_all()
        assert [m["data"]["people_ahead"] for m in events(mine, 1)] == [1]    # being served still counts
        act(q, first["id"], "start")
        act(q, first["id"], "complete")
        relay_all()
        last = events(mine, 2)[-1]["data"]
        assert last["people_ahead"] == 0 and last["status"] == "WAITING"


def test_patient_sees_own_final_status_when_they_leave(q):
    me = my_patient_id(q)
    tok = walk_in(q, me).json()
    relay_all()
    with open_ws(q.env.patient, q) as mine:
        assert act(q, tok["id"], "cancel", q.env.patient).status_code == 200
        relay_all()
        data = events(mine, 1)[-1]["data"]
        assert data["status"] == "CANCELLED" and data["people_ahead"] is None


def test_other_doctors_queue_events_do_not_reach_this_doctor(q):
    from tests.integration.test_clinic_management import mk_dept, mk_doctor

    other = mk_doctor(q.env, mk_dept(q.env, "Other", "O"), "Dr Other")
    relay_all()
    with open_ws(q.env.doctor, q) as doctor, open_ws(q.env.admin, q) as admin:
        walk_in(q, mk_patient(q, "Pat Other"), doctor_id=other["id"])
        relay_all()
        assert len(events(admin, 1)) == 1                        # staff see every doctor
        silent(doctor)                                           # this doctor sees only their own


def test_appointment_events_reach_staff_doctor_and_the_booking_patient_only(q):
    stranger_client = second_patient(q)
    relay_all()
    with open_ws(q.env.receptionist, q) as staff, open_ws(q.env.doctor, q) as doctor, \
            open_ws(q.env.patient, q) as mine, open_ws(stranger_client, q) as other:
        first = slots(q)[0]["starts_at"]
        r = book(q, first)
        assert r.status_code == 201
        relay_all()
        for ws in (staff, doctor, mine):
            msgs = events(ws, 1)
            assert kinds(msgs) == ["appointment.updated"]
            assert msgs[0]["data"] == {"appointment_id": r.json()["id"], "doctor_id": q.doctor["id"],
                                       "status": "CONFIRMED", "starts_at": msgs[0]["data"]["starts_at"],
                                       "change": "booked"}
        silent(other)
        assert post(q.env.patient, f"{q.env.base}/appointments/{r.json()['id']}/cancel").status_code == 200
        relay_all()
        assert events(mine, 1)[-1]["data"]["change"] == "cancelled"


# ------------------------------------------------------------ outbox guarantees
def test_booking_writes_outbox_rows_and_a_rejected_booking_writes_none(q, owner_engine):
    first = slots(q)[0]["starts_at"]
    assert book(q, first).status_code == 201
    with owner_engine.connect() as c:
        n = c.execute(text("select count(*) from outbox_events where event_type='appointment.updated'")).scalar()
    assert n == 3                                                # staff + doctor + the patient's own channel
    other = second_patient(q)
    assert book(q, first, client=other).status_code == 409       # lost the race: rolled back
    with owner_engine.connect() as c:
        assert c.execute(text("select count(*) from outbox_events")).scalar() == n


def test_relay_loses_nothing_when_the_broker_fails_midway(q, owner_engine):
    me = my_patient_id(q)
    relay_all()
    for i in range(3):
        walk_in(q, mk_patient(q, f"Patient Number{i}"))
    walk_in(q, me)
    with owner_engine.connect() as c:
        pending = c.execute(text("select id from outbox_events where published_at is null order by version")).all()
    pending_ids = [str(r[0]) for r in pending]
    assert len(pending_ids) > 4

    delivered: list[str] = []

    def flaky(channel: str, message: str) -> None:
        if len(delivered) == 2:
            raise ConnectionError("broker down")
        delivered.append(json.loads(message)["id"])

    with pytest.raises(RelayPublishError) as err:
        relay_batch(get_sessionmaker(), flaky, 100)
    assert err.value.published == 2 and len(delivered) == 2

    def healthy(channel: str, message: str) -> None:
        delivered.append(json.loads(message)["id"])

    while relay_batch(get_sessionmaker(), healthy, 100):
        pass
    assert delivered == pending_ids                              # every event, once, in order, none lost


def test_total_broker_outage_keeps_every_event_until_it_recovers(q, owner_engine):
    relay_all()
    walk_in(q, mk_patient(q))

    def down(channel: str, message: str) -> None:
        raise ConnectionError("broker down")

    for _ in range(3):
        with pytest.raises(RelayPublishError):
            relay_batch(get_sessionmaker(), down, 100)
    with owner_engine.connect() as c:
        pending = c.execute(text("select count(*) from outbox_events where published_at is null")).scalar()
    assert pending > 0
    assert relay_all() == pending


def test_crash_before_marking_published_redelivers_with_the_same_event_ids(q, owner_engine):
    relay_all()
    walk_in(q, mk_patient(q))
    first: list[str] = []
    relay_batch(get_sessionmaker(), lambda ch, m: first.append(json.loads(m)["id"]), 100)
    assert first
    with owner_engine.begin() as c:                              # simulate: published, then crashed before commit
        c.execute(text("update outbox_events set published_at = null"))
    again: list[str] = []
    relay_batch(get_sessionmaker(), lambda ch, m: again.append(json.loads(m)["id"]), 100)
    assert sorted(first) == sorted(again)                        # at-least-once; ids let clients deduplicate


def test_relay_publishes_in_version_order_and_marks_rows(q, owner_engine):
    relay_all()
    for i in range(3):
        walk_in(q, mk_patient(q, f"Ordered Patient{i}"))
    seen: list[int] = []
    relay_batch(get_sessionmaker(), lambda ch, m: seen.append(json.loads(m)["version"]), 100)
    assert seen == sorted(seen) and len(seen) == len(set(seen)) and seen
    with owner_engine.connect() as c:
        assert c.execute(text("select count(*) from outbox_events where published_at is null")).scalar() == 0


def test_purge_removes_only_old_published_events(q, owner_engine):
    from app.workers.outbox_relay import purge_published

    walk_in(q, mk_patient(q))
    relay_all()
    walk_in(q, mk_patient(q, "Still Pending"))                   # unpublished: must survive
    with owner_engine.begin() as c:
        c.execute(text("update outbox_events set published_at = now() - interval '30 days' "
                       "where published_at is not null"))
    removed = purge_published(get_sessionmaker(), 7)
    assert removed > 0
    with owner_engine.connect() as c:
        left = c.execute(text("select count(*) from outbox_events where published_at is null")).scalar()
        old = c.execute(text("select count(*) from outbox_events where published_at is not null")).scalar()
    assert left > 0 and old == 0


def test_row_level_security_isolates_outbox_rows_by_clinic(owner_engine):
    """Uses the application's own restricted DB role, so RLS is genuinely in force."""
    a = setup_bookable(owner_engine, slug="alpha", link_doctor=True)
    b = setup_bookable(owner_engine, slug="beta", link_doctor=True)
    walk_in(a, mk_patient(a))
    count = select(func.count()).select_from(OutboxEvent)
    with get_sessionmaker()() as db:
        set_rls_context(db, clinic_id=uuid.UUID(b.env.cid))
        assert db.scalar(count) == 0                             # beta cannot see alpha's events
        set_rls_context(db, clinic_id=uuid.UUID(a.env.cid))
        assert db.scalar(count) > 0
        set_rls_context(db)                                      # no context at all: fail closed
        assert db.scalar(count) == 0


# ------------------------------------------------------------- revocation while connected
def test_connection_is_closed_when_membership_is_revoked(q, owner_engine, monkeypatch):
    monkeypatch.setattr(get_settings(), "ws_revalidate_seconds", 1)
    with open_ws(q.env.patient, q) as ws:
        with owner_engine.begin() as c:
            c.execute(text("update clinic_memberships set is_active = false where role = 'PATIENT'"))
        time.sleep(1.8)
        with pytest.raises(WebSocketDisconnect):
            ws.send_json({"type": "ping"})
            ws.receive_json()
