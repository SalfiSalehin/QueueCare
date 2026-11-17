"""Phase 8: notifications. Idempotent creation in the caller's transaction, a retrying at-least-once worker,
reminders, the in-app inbox, and isolation. All data is synthetic; providers are mocks (nothing is sent).

The worker is driven explicitly (NOTIFICATION_WORKER_ENABLED=false in the test env), with an injected `now`
so retry/back-off behaviour does not depend on real waiting.
"""
from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.database import get_sessionmaker, set_rls_context
from app.services import notification_service
from app.services.notification_providers import ProviderError, get_providers
from app.services.notification_service import enqueue
from app.workers.notification_worker import claim_batch, dispatch_batch, purge_old, schedule_reminders
from tests.integration.test_appointments import book, insert_appt, my_patient_id, setup_bookable, slots
from tests.integration.test_queue import act, walk_in
from tests.conftest import csrf

FACTORY = get_sessionmaker()


@pytest.fixture(autouse=True)
def clean_providers():
    for provider in get_providers().values():
        provider.reset()
    yield
    for provider in get_providers().values():
        provider.reset()


@pytest.fixture
def q(owner_engine):
    return setup_bookable(owner_engine, slug="alpha", link_doctor=True)


def user_id(owner_engine, email: str) -> str:
    with owner_engine.connect() as c:
        return str(c.execute(text("select id from users where email=:e"), {"e": email}).scalar())


def prepare_patient(owner_engine, q, *, verified=True, phone: str | None = None) -> str:
    email = "patient-alpha@example.com"
    with owner_engine.connect() as c:
        c.execute(text("update users set email_verified=:v, phone=:p where email=:e"),
                  {"v": verified, "p": phone, "e": email})
    return user_id(owner_engine, email)


def rows(owner_engine, where: str = "true", **params) -> list:
    with owner_engine.connect() as c:
        return list(c.execute(text(
            "select channel, type, status, attempts, next_attempt_at, last_error, idempotency_key, payload, clinic_id "
            f"from notifications where {where} order by created_at, channel"), params))


def first_slot(q) -> str:
    return slots(q)[0]["starts_at"]


def run_worker(**kw):
    return dispatch_batch(FACTORY, **kw)


# ============================================================== creation (booking events)
def test_booking_creates_an_in_app_and_an_email_notification_for_the_patient(q, owner_engine):
    prepare_patient(owner_engine, q)
    assert book(q, first_slot(q)).status_code == 201
    got = {r.channel: r for r in rows(owner_engine, "type='appointment.booked'")}
    assert set(got) == {"IN_APP", "EMAIL"}                    # no SMS: not a time-critical type
    assert got["IN_APP"].status == "SENT" and got["EMAIL"].status == "PENDING"


def test_an_unverified_email_address_gets_in_app_only(q, owner_engine):
    prepare_patient(owner_engine, q, verified=False)
    assert book(q, first_slot(q)).status_code == 201
    assert [r.channel for r in rows(owner_engine)] == ["IN_APP"]


def test_staff_cancelling_notifies_the_patient(q, owner_engine):
    prepare_patient(owner_engine, q)
    appt = book(q, first_slot(q)).json()
    r = q.env.receptionist.post(f"{q.env.base}/appointments/{appt['id']}/cancel", json={"reason": "doctor ill"},
                                headers=csrf(q.env.receptionist))
    assert r.status_code == 200, r.text
    assert {x.type for x in rows(owner_engine)} == {"appointment.booked", "appointment.cancelled"}


def test_a_patient_without_an_account_is_simply_not_notified(q, owner_engine):
    r = q.env.receptionist.post(f"{q.env.base}/patients", json={"full_name": "Walk Only"},
                                headers=csrf(q.env.receptionist))
    assert r.status_code == 201, r.text
    booked = q.env.receptionist.post(
        f"{q.env.base}/appointments", headers=csrf(q.env.receptionist),
        json={"doctor_id": q.doctor["id"], "starts_at": first_slot(q), "patient_id": r.json()["id"]})
    assert booked.status_code == 201, booked.text
    assert rows(owner_engine) == []


def test_enqueue_is_idempotent(q, owner_engine):
    prepare_patient(owner_engine, q)
    uid = uuid.UUID(user_id(owner_engine, "patient-alpha@example.com"))
    payload = {"clinic_name": "C", "doctor_name": "D", "starts_at": datetime.now(UTC).isoformat(), "tz": "UTC"}

    def once() -> int:
        with FACTORY() as db:
            set_rls_context(db, platform=True)
            n = enqueue(db, clinic_id=uuid.UUID(q.env.cid), user_id=uid, kind="appointment.booked",
                        entity_key="same-event", payload=payload)
            db.commit()
            return n
    assert once() == 2 and once() == 0                         # IN_APP + EMAIL the first time, nothing the second
    assert len(rows(owner_engine, "idempotency_key like 'appointment.booked:same-event:%'")) == 2


def test_a_booking_that_loses_the_race_gets_a_409_and_no_notification(q, owner_engine):
    """Regression: the notification savepoint used to flush the caller's pending booking, so the database's
    double-booking constraint fired inside it, was swallowed, and the request ended as a 500."""
    from tests.conftest import new_client, signup
    prepare_patient(owner_engine, q)
    slot = first_slot(q)
    assert book(q, slot).status_code == 201
    rival = new_client()
    signup(rival, "rival-alpha@example.com")
    assert rival.post(f"{q.env.base}/join", headers=csrf(rival)).status_code == 204
    assert book(q, slot, rival).status_code == 409
    assert len(rows(owner_engine, "type='appointment.booked' and channel='IN_APP'")) == 1


def test_a_failure_while_enqueueing_never_breaks_the_booking(q, owner_engine, monkeypatch):
    prepare_patient(owner_engine, q)

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(notification_service, "enqueue", boom)
    assert book(q, first_slot(q)).status_code == 201
    assert rows(owner_engine) == []


# ====================================================================== delivery worker
def test_worker_delivers_email_once_and_marks_it_sent(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    stats = run_worker()
    assert (stats.claimed, stats.sent) == (1, 1)
    sent = list(get_providers()["EMAIL"].outbox)
    assert len(sent) == 1 and sent[0].to == "patient-alpha@example.com" and sent[0].kind == "appointment.booked"
    assert "Dr Bookable" in sent[0].body and "Clinic alpha" in sent[0].body
    assert run_worker().claimed == 0                           # nothing left to do
    assert len(get_providers()["EMAIL"].outbox) == 1
    email = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert email.status == "SENT" and email.attempts == 1 and email.last_error is None


def test_transient_failure_is_retried_with_backoff_then_succeeds(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    t0 = datetime.now(UTC)
    provider = get_providers()["EMAIL"]
    provider.failure = lambda m: ProviderError("temporarily down")
    stats = run_worker(now=t0, backoff_base=30)
    assert (stats.claimed, stats.retried, stats.sent) == (1, 1, 0)
    row = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert row.status == "PENDING" and row.attempts == 1 and row.last_error == "temporarily down"
    assert abs((row.next_attempt_at - (t0 + timedelta(seconds=30))).total_seconds()) < 2
    assert run_worker(now=t0 + timedelta(seconds=10)).claimed == 0          # not due yet
    provider.failure = None
    stats = run_worker(now=t0 + timedelta(seconds=31))
    assert stats.sent == 1
    row = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert row.status == "SENT" and row.attempts == 2 and row.last_error is None
    assert len(provider.outbox) == 1


def test_retries_stop_after_the_maximum_and_the_row_is_failed_with_a_reason(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    get_providers()["EMAIL"].failure = lambda m: ProviderError("still down")
    now = datetime.now(UTC)
    for _ in range(3):
        run_worker(now=now, max_attempts=3, backoff_base=30)
        now += timedelta(hours=2)
    row = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert row.status == "FAILED" and row.attempts == 3 and row.last_error == "still down"
    assert run_worker(now=now, max_attempts=3).claimed == 0                  # a failed row is not retried again


def test_a_permanent_error_fails_immediately(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    get_providers()["EMAIL"].failure = lambda m: ProviderError("invalid address", permanent=True)
    stats = run_worker(max_attempts=5)
    assert (stats.retried, stats.failed) == (0, 1)
    row = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert row.status == "FAILED" and row.attempts == 1


def test_unexpected_exceptions_do_not_leak_their_text_into_the_database(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))

    def boom(m):
        raise RuntimeError("could not reach patient-alpha@example.com")
    get_providers()["EMAIL"].failure = boom
    run_worker()
    row = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert row.last_error == "RuntimeError" and "@" not in row.last_error


def test_a_crashed_worker_leaves_a_lease_and_the_row_is_picked_up_later(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    t0 = datetime.now(UTC)
    claims, _ = claim_batch(FACTORY, t0, 10, max_attempts=5, lease_seconds=120)   # claims, then "crashes"
    assert len(claims) == 1
    assert run_worker(now=t0 + timedelta(seconds=30)).claimed == 0                # still leased
    stats = run_worker(now=t0 + timedelta(seconds=121), lease_seconds=120)
    assert stats.sent == 1
    row = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert row.attempts == 2                                                       # the lost try is counted


def test_a_row_that_keeps_killing_workers_is_eventually_failed(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    now = datetime.now(UTC)
    for _ in range(3):
        claim_batch(FACTORY, now, 10, max_attempts=3, lease_seconds=60)            # claimed, never finished
        now += timedelta(minutes=5)
    stats = run_worker(now=now, max_attempts=3)
    assert stats.sent == 0 and stats.failed == 1
    row = next(r for r in rows(owner_engine) if r.channel == "EMAIL")
    assert row.status == "FAILED" and "exhausted" in row.last_error
    assert not get_providers()["EMAIL"].outbox


def test_concurrent_workers_never_send_the_same_notification_twice(q, owner_engine):
    uid = prepare_patient(owner_engine, q)
    payload = ('{"clinic_name":"C","doctor_name":"D","starts_at":"2026-12-01T09:00:00+00:00","tz":"UTC"}')
    with owner_engine.connect() as c:
        for i in range(40):
            c.execute(text(
                "insert into notifications (clinic_id, user_id, channel, type, idempotency_key, payload) "
                "values (:c, :u, 'EMAIL', 'appointment.booked', :k, cast(:p as jsonb))"),
                {"c": q.env.cid, "u": uid, "k": f"bulk-{i}", "p": payload})
    errors: list[Exception] = []

    def work() -> None:
        try:
            for _ in range(8):
                dispatch_batch(FACTORY, batch_size=5)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=work) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    keys = [m.idempotency_key for m in get_providers()["EMAIL"].outbox]
    assert len(keys) == 40 and len(set(keys)) == 40
    assert all(r.status == "SENT" for r in rows(owner_engine, "channel='EMAIL'"))


def test_the_worker_serves_every_clinic(owner_engine):
    a = setup_bookable(owner_engine, slug="alpha", link_doctor=True)
    b = setup_bookable(owner_engine, slug="beta", link_doctor=True)
    for env, email in ((a, "patient-alpha@example.com"), (b, "patient-beta@example.com")):
        with owner_engine.connect() as c:
            c.execute(text("update users set email_verified=true where email=:e"), {"e": email})
        assert book(env, first_slot(env)).status_code == 201
    assert run_worker().sent == 2
    assert {m.to for m in get_providers()["EMAIL"].outbox} == {"patient-alpha@example.com", "patient-beta@example.com"}


# ======================================================================== reminders
def future(hours: float) -> datetime:
    return (datetime.now(UTC) + timedelta(hours=hours)).replace(microsecond=0)


def test_reminders_are_created_once_for_appointments_inside_the_window(q, owner_engine):
    prepare_patient(owner_engine, q, phone="+10000000000")
    pid = my_patient_id(q)
    soon = insert_appt(owner_engine, q, future(5), pid)
    insert_appt(owner_engine, q, future(24 * 3), pid)                       # too far away
    insert_appt(owner_engine, q, future(8), pid, status="CANCELLED")        # not confirmed
    now = datetime.now(UTC)
    assert schedule_reminders(FACTORY, now, 24) == 3                        # IN_APP + EMAIL + SMS for one appointment
    assert schedule_reminders(FACTORY, now, 24) == 0                        # idempotent
    got = rows(owner_engine, "type='appointment.reminder'")
    assert {r.channel for r in got} == {"IN_APP", "EMAIL", "SMS"}
    assert all(r.payload["appointment_id"] == soon for r in got)


def test_a_reminder_is_dropped_if_the_appointment_was_cancelled_before_it_is_sent(q, owner_engine):
    prepare_patient(owner_engine, q)
    appt = insert_appt(owner_engine, q, future(5), my_patient_id(q))
    schedule_reminders(FACTORY, datetime.now(UTC), 24)
    with owner_engine.connect() as c:
        c.execute(text("update appointments set status='CANCELLED' where id=:i"), {"i": appt})
    run_worker()          # also delivers the booked/cancelled emails created by my_patient_id(); ignore those
    row = next(r for r in rows(owner_engine, "type='appointment.reminder'") if r.channel == "EMAIL")
    assert row.status == "FAILED" and row.last_error.startswith("skipped")
    assert all(m.kind != "appointment.reminder" for m in get_providers()["EMAIL"].outbox)


def test_sms_reminder_is_delivered_through_the_sms_provider(q, owner_engine):
    prepare_patient(owner_engine, q, verified=False, phone="+10000000000")
    insert_appt(owner_engine, q, future(5), my_patient_id(q))
    schedule_reminders(FACTORY, datetime.now(UTC), 24)
    assert run_worker().sent == 1
    sms = list(get_providers()["SMS"].outbox)
    assert len(sms) == 1 and sms[0].to == "+10000000000" and not get_providers()["EMAIL"].outbox


# ================================================================== queue "your turn"
def test_calling_a_patient_notifies_them_and_a_second_call_notifies_again(q, owner_engine):
    prepare_patient(owner_engine, q, phone="+10000000000")
    token = walk_in(q, my_patient_id(q)).json()
    assert act(q, token["id"], "call").status_code == 200
    first = rows(owner_engine, "type='queue.called'")
    assert {r.channel for r in first} == {"IN_APP", "EMAIL", "SMS"}
    assert first[0].payload["token_label"] == token["token_label"]
    assert act(q, token["id"], "skip").status_code == 200          # the patient did not show up at the desk
    assert act(q, token["id"], "requeue").status_code == 200
    assert act(q, token["id"], "call").status_code == 200
    assert len(rows(owner_engine, "type='queue.called' and channel='IN_APP'")) == 2


def test_a_token_for_someone_without_an_account_notifies_nobody(q, owner_engine):
    from tests.integration.test_queue import mk_patient
    token = walk_in(q, mk_patient(q, "No Account")).json()
    assert act(q, token["id"], "call").status_code == 200
    assert rows(owner_engine, "type='queue.called'") == []


# ============================================================================ inbox API
def inbox(q, client=None, **params):
    return (client or q.env.patient).get(f"{q.env.base}/notifications", params=params)


def test_the_patient_reads_marks_and_counts_their_notifications(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    page = inbox(q).json()
    assert page["total"] == 1 and page["items"][0]["read"] is False
    item = page["items"][0]
    assert item["title"] == "Appointment booked" and "Dr Bookable" in item["body"]
    assert q.env.patient.get(f"{q.env.base}/notifications/unread-count").json() == {"count": 1}
    r = q.env.patient.post(f"{q.env.base}/notifications/{item['id']}/read", headers=csrf(q.env.patient))
    assert r.status_code == 200 and r.json()["read"] is True
    assert q.env.patient.get(f"{q.env.base}/notifications/unread-count").json() == {"count": 0}
    assert inbox(q, unread=True).json()["total"] == 0


def test_read_all_marks_everything(q, owner_engine):
    prepare_patient(owner_engine, q)
    slot = slots(q)
    book(q, slot[0]["starts_at"])
    book(q, slot[1]["starts_at"])
    r = q.env.patient.post(f"{q.env.base}/notifications/read-all", headers=csrf(q.env.patient))
    assert r.json() == {"count": 2}
    assert q.env.patient.get(f"{q.env.base}/notifications/unread-count").json() == {"count": 0}


def test_other_members_never_see_or_touch_the_patients_notifications(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    nid = inbox(q).json()["items"][0]["id"]
    for who in (q.env.receptionist, q.env.admin, q.env.doctor):
        assert inbox(q, who).json()["total"] == 0
        assert who.post(f"{q.env.base}/notifications/{nid}/read", headers=csrf(who)).status_code == 404


def test_a_member_of_another_clinic_cannot_reach_this_inbox(q, owner_engine):
    beta = setup_bookable(owner_engine, slug="beta")
    assert beta.env.patient.get(f"{q.env.base}/notifications").status_code == 404
    from tests.conftest import new_client
    assert new_client().get(f"{q.env.base}/notifications").status_code == 401


def test_the_inbox_only_lists_in_app_rows(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))                                      # creates IN_APP and EMAIL rows
    assert inbox(q).json()["total"] == 1


# ================================================================================ retention
def test_old_finished_notifications_are_purged_but_pending_ones_are_kept(q, owner_engine):
    prepare_patient(owner_engine, q)
    book(q, first_slot(q))
    with owner_engine.connect() as c:
        c.execute(text("update notifications set created_at = now() - interval '90 days'"))
    assert purge_old(FACTORY, 30) == 1                          # the IN_APP (SENT) row
    assert [r.channel for r in rows(owner_engine)] == ["EMAIL"]  # PENDING email is not purged
