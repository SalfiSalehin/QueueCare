"""Database-level guarantees: Row-Level Security, tenant FKs, audit immutability, no double booking.

These bypass the API on purpose: they prove the protections hold even if application code is wrong.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.database import get_engine, set_rls_context

A, B = uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def seeded(owner_engine):
    ids = {}
    with owner_engine.begin() as c:
        for cid, slug in ((A, "rls-a"), (B, "rls-b")):
            c.execute(text("insert into clinics(id,name,slug,status) values (:i,:n,:s,'ACTIVE')"),
                      {"i": cid, "n": slug.upper(), "s": slug})
            dept, doc, pat = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            c.execute(text("insert into departments(id,clinic_id,name,queue_prefix) values (:d,:c,'General','A')"),
                      {"d": dept, "c": cid})
            c.execute(text("insert into doctors(id,clinic_id,department_id,display_name) values (:x,:c,:d,'Dr Synthetic')"),
                      {"x": doc, "c": cid, "d": dept})
            c.execute(text("insert into patients(id,clinic_id,full_name) values (:p,:c,'Synthetic Patient')"),
                      {"p": pat, "c": cid})
            ids[cid] = {"dept": dept, "doctor": doc, "patient": pat}
    return ids


def app_session() -> Session:
    return Session(get_engine())


def test_rls_fails_closed_without_context(seeded):
    with app_session() as db:
        for table in ("departments", "doctors", "patients", "clinic_memberships"):
            assert db.execute(text(f"select count(*) from {table}")).scalar() == 0, table


def test_rls_scopes_reads_to_the_bound_clinic(seeded):
    with app_session() as db:
        set_rls_context(db, clinic_id=A)
        rows = db.execute(text("select distinct clinic_id from departments")).scalars().all()
        assert rows == [A]
        assert db.execute(text("select count(*) from patients where clinic_id = :b"), {"b": B}).scalar() == 0


def test_rls_blocks_cross_tenant_insert_and_update(seeded):
    with app_session() as db:
        set_rls_context(db, clinic_id=A)
        with pytest.raises(DBAPIError):
            db.execute(text("insert into departments(clinic_id,name,queue_prefix) values (:b,'Hack','H')"), {"b": B})
        db.rollback()
        set_rls_context(db, clinic_id=A)
        res = db.execute(text("update departments set name='pwned' where clinic_id = :b"), {"b": B})
        assert res.rowcount == 0
        db.rollback()


def test_rls_context_survives_commit_via_session_hook(seeded):
    with app_session() as db:
        set_rls_context(db, clinic_id=A)
        db.execute(text("select 1"))
        db.commit()                                   # context is transaction-local; hook must re-apply it
        assert db.execute(text("select count(*) from departments")).scalar() == 1
        db.commit()
        assert db.execute(text("select count(*) from departments where clinic_id = :b"), {"b": B}).scalar() == 0


def test_platform_flag_is_the_only_cross_tenant_path(seeded):
    with app_session() as db:
        set_rls_context(db, platform=True)
        assert db.execute(text("select count(*) from departments")).scalar() == 2


def test_context_does_not_leak_between_pooled_connections(seeded):
    with app_session() as db:
        set_rls_context(db, clinic_id=A)
        db.execute(text("select 1"))
        db.commit()
    with app_session() as db2:                         # fresh session, possibly same pooled connection
        assert db2.execute(text("select count(*) from departments")).scalar() == 0


def test_app_role_is_not_privileged(owner_engine):
    with owner_engine.connect() as c:
        row = c.execute(text("select rolsuper, rolbypassrls from pg_roles where rolname='queuecare_app'")).one()
    assert tuple(row) == (False, False)


def test_audit_log_is_append_only_for_app_role(seeded):
    with app_session() as db:
        db.execute(text("insert into audit_logs(action) values ('test.event')"))
        db.commit()
        for sql in ("update audit_logs set action='tampered'", "delete from audit_logs"):
            with pytest.raises(ProgrammingError):
                db.execute(text(sql))
            db.rollback()


def test_composite_fk_blocks_cross_tenant_references(owner_engine, seeded):
    with pytest.raises(IntegrityError), owner_engine.begin() as c:
        c.execute(text("insert into doctors(clinic_id,department_id,display_name) values (:a,:dept_b,'Cross')"),
                  {"a": A, "dept_b": seeded[B]["dept"]})
    with pytest.raises(IntegrityError), owner_engine.begin() as c:
        c.execute(text("""insert into appointments(clinic_id,doctor_id,patient_id,starts_at,ends_at)
                          values (:a,:doc,:pat_b,'2030-01-01 09:00+00','2030-01-01 09:20+00')"""),
                  {"a": A, "doc": seeded[A]["doctor"], "pat_b": seeded[B]["patient"]})


def _book(conn, clinic, doctor, patient, start, end, status="CONFIRMED"):
    conn.execute(text("""insert into appointments(clinic_id,doctor_id,patient_id,starts_at,ends_at,status)
                         values (:c,:d,:p,:s,:e,:st)"""),
                 {"c": clinic, "d": doctor, "p": patient, "s": start, "e": end, "st": status})


def test_exclusion_constraint_prevents_double_booking(owner_engine, seeded):
    s = seeded[A]
    with owner_engine.begin() as c:
        _book(c, A, s["doctor"], s["patient"], "2030-01-01 09:00+00", "2030-01-01 09:20+00")
    with pytest.raises(IntegrityError, match="appointments_no_doctor_overlap"), owner_engine.begin() as c:
        _book(c, A, s["doctor"], s["patient"], "2030-01-01 09:10+00", "2030-01-01 09:30+00")
    with owner_engine.begin() as c:                    # adjacent slots are fine: ranges are [start, end)
        _book(c, A, s["doctor"], s["patient"], "2030-01-01 09:20+00", "2030-01-01 09:40+00")
    with owner_engine.begin() as c:
        c.execute(text("update appointments set status='CANCELLED' where starts_at='2030-01-01 09:00+00'"))
        _book(c, A, s["doctor"], s["patient"], "2030-01-01 09:00+00", "2030-01-01 09:20+00")  # slot freed


def test_concurrent_double_booking_has_exactly_one_winner(owner_engine, seeded):
    s = seeded[A]
    n = 8
    barrier = threading.Barrier(n)
    results: list[str] = []
    lock = threading.Lock()

    def attempt():
        barrier.wait()
        try:
            with owner_engine.begin() as c:
                _book(c, A, s["doctor"], s["patient"], "2030-02-01 10:00+00", "2030-02-01 10:20+00")
            outcome = "ok"
        except IntegrityError:
            outcome = "conflict"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("conflict") == n - 1
    with owner_engine.connect() as c:
        assert c.execute(text("select count(*) from appointments")).scalar() == 1


def test_token_uniqueness_and_check_constraints(owner_engine, seeded):
    s = seeded[A]
    sql = text("""insert into queue_tokens(clinic_id,doctor_id,patient_id,queue_date,prefix,sequence_no,token_label,source)
                  values (:c,:d,:p,'2030-01-01','A',1,'A-001','WALK_IN')""")
    args = {"c": A, "d": s["doctor"], "p": s["patient"]}
    with owner_engine.begin() as c:
        c.execute(sql, args)
    with pytest.raises(IntegrityError), owner_engine.begin() as c:
        c.execute(sql, args)
    with pytest.raises(IntegrityError), owner_engine.begin() as c:       # end before start
        _book(c, A, s["doctor"], s["patient"], "2030-03-01 10:00+00", "2030-03-01 09:00+00")
    with pytest.raises(IntegrityError), owner_engine.begin() as c:       # invalid status value
        _book(c, A, s["doctor"], s["patient"], "2030-03-02 10:00+00", "2030-03-02 10:20+00", status="BOGUS")


def test_updated_at_trigger_advances(owner_engine, seeded):
    with owner_engine.begin() as c:
        c.execute(text("update clinics set name='Renamed' where id=:i"), {"i": A})
        assert c.execute(text("select updated_at > created_at from clinics where id=:i"), {"i": A}).scalar()


# ----------------------------------------------------------------- Phase 3 constraints (migration 0002)
def _schedule(conn, clinic, doctor, day, start, end, valid_from=None, valid_to=None):
    conn.execute(text("""insert into doctor_schedules(clinic_id,doctor_id,day_of_week,start_time,end_time,valid_from,valid_to)
                         values (:c,:d,:day,:s,:e,:vf,:vt)"""),
                 {"c": clinic, "d": doctor, "day": day, "s": start, "e": end, "vf": valid_from, "vt": valid_to})


def test_schedule_windows_cannot_overlap_at_database_level(owner_engine, seeded):
    doc = seeded[A]["doctor"]
    with owner_engine.begin() as c:
        _schedule(c, A, doc, 0, "09:00", "12:00")
        _schedule(c, A, doc, 0, "12:00", "15:00")                       # touching edges are fine
        _schedule(c, A, doc, 1, "09:00", "12:00")                       # other weekday
        _schedule(c, A, doc, 2, "09:00", "12:00", "2030-01-01", "2030-01-31")
        _schedule(c, A, doc, 2, "09:00", "12:00", "2030-02-01", None)   # disjoint validity
    for args in ((0, "11:00", "13:00", None, None), (0, "09:00", "12:00", None, None),
                 (2, "10:00", "11:00", "2030-01-15", "2030-01-20"), (2, "10:00", "11:00", None, None)):
        with pytest.raises(IntegrityError, match="doctor_schedules_no_overlap"), owner_engine.begin() as c:
            _schedule(c, A, doc, *args)


def test_concurrent_overlapping_schedules_have_one_winner(owner_engine, seeded):
    doc = seeded[A]["doctor"]
    n, barrier, results, lock = 6, threading.Barrier(6), [], threading.Lock()

    def attempt():
        barrier.wait()
        try:
            with owner_engine.begin() as c:
                _schedule(c, A, doc, 4, "09:00", "12:00")
            outcome = "ok"
        except IntegrityError:
            outcome = "conflict"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("conflict") == n - 1


def test_one_doctor_profile_per_account_per_clinic(owner_engine, seeded):
    with owner_engine.begin() as c:
        uid = uuid.uuid4()
        c.execute(text("insert into users(id,email,password_hash,full_name) values (:i,'doc@example.com','x','Doc')"),
                  {"i": uid})
        c.execute(text("update doctors set user_id=:u where id=:d"), {"u": uid, "d": seeded[A]["doctor"]})
        # the same account may have a profile in a DIFFERENT clinic
        c.execute(text("update doctors set user_id=:u where id=:d"), {"u": uid, "d": seeded[B]["doctor"]})
    with pytest.raises(IntegrityError, match="uq_doctors_clinic_user"), owner_engine.begin() as c:
        c.execute(text("""insert into doctors(clinic_id,department_id,display_name,user_id)
                          values (:c,:d,'Dr Twin',:u)"""),
                  {"c": A, "d": seeded[A]["dept"], "u": uid})
