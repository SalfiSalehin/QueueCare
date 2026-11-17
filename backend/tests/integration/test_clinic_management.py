"""Phase 3: settings, departments, doctors, schedules, time off, staff membership."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time

import pytest

from app.services.clinic_admin_service import schedules_overlap
from tests.conftest import create_active_clinic, csrf, new_client, signup


@dataclass
class Env:
    cid: str
    admin: object
    receptionist: object
    doctor: object
    patient: object
    emails: dict

    @property
    def base(self) -> str:
        return f"/api/v1/clinics/{self.cid}"


def setup_clinic(owner_engine, slug: str = "alpha") -> Env:
    admin = new_client()
    signup(admin, f"admin-{slug}@example.com")
    cid = create_active_clinic(owner_engine, admin, f"clinic-{slug}", f"Clinic {slug}")
    clients, emails = {}, {}
    for role in ("RECEPTIONIST", "DOCTOR"):
        c = new_client()
        email = f"{role.lower()}-{slug}@example.com"
        signup(c, email)
        r = admin.post(f"/api/v1/clinics/{cid}/members", json={"email": email, "role": role}, headers=csrf(admin))
        assert r.status_code == 201, r.text
        clients[role], emails[role] = c, email
    patient = new_client()
    signup(patient, f"patient-{slug}@example.com")
    assert patient.post(f"/api/v1/clinics/{cid}/join", headers=csrf(patient)).status_code == 204
    return Env(cid, admin, clients["RECEPTIONIST"], clients["DOCTOR"], patient, emails)


def post(c, url, body=None, **kw):
    return c.post(url, json=body, headers=csrf(c), **kw)


def patch(c, url, body):
    return c.patch(url, json=body, headers=csrf(c))


def delete(c, url):
    return c.delete(url, headers=csrf(c))


def mk_dept(env: Env, name="General", prefix="G") -> str:
    r = post(env.admin, f"{env.base}/departments", {"name": name, "queue_prefix": prefix})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def mk_doctor(env: Env, dept: str, name="Dr Synthetic", **extra) -> dict:
    r = post(env.admin, f"{env.base}/doctors", {"display_name": name, "department_id": dept, **extra})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def env(owner_engine) -> Env:
    return setup_clinic(owner_engine)


# ------------------------------------------------------------------- pure unit
def test_schedule_overlap_rules():
    t = time
    assert schedules_overlap(t(9), t(12), None, None, t(11), t(14), None, None)
    assert not schedules_overlap(t(9), t(12), None, None, t(12), t(15), None, None)       # touching edges
    assert schedules_overlap(t(9), t(12), None, None, t(9), t(12), None, None)
    assert not schedules_overlap(t(9), t(12), date(2030, 1, 1), date(2030, 1, 31),
                                 t(9), t(12), date(2030, 2, 1), None)                      # disjoint validity
    assert schedules_overlap(t(9), t(12), date(2030, 1, 1), None, t(9), t(12), date(2030, 6, 1), date(2030, 7, 1))


# -------------------------------------------------------------------- settings
def test_clinic_detail_has_default_settings(env):
    r = env.patient.get(env.base)
    assert r.status_code == 200
    assert r.json()["settings"] == {"booking_horizon_days": 60, "min_notice_minutes": 60,
                                    "cancellation_cutoff_hours": 2, "queue_policy": "APPOINTMENT_FIRST",
                                    "walkin_priority_enabled": False}


def test_admin_updates_settings_and_it_persists(env):
    body = {"name": "Renamed Clinic", "timezone": "Asia/Dhaka",
            "settings": {"booking_horizon_days": 30, "queue_policy": "FIFO", "walkin_priority_enabled": True}}
    r = patch(env.admin, env.base, body)
    assert r.status_code == 200, r.text
    got = env.receptionist.get(env.base).json()
    assert got["name"] == "Renamed Clinic" and got["timezone"] == "Asia/Dhaka"
    assert got["settings"]["queue_policy"] == "FIFO" and got["settings"]["booking_horizon_days"] == 30
    assert got["settings"]["min_notice_minutes"] == 60            # unspecified fields fall back to defaults


@pytest.mark.parametrize("body", [
    {"timezone": "Mars/Olympus"},
    {"settings": {"booking_horizon_days": 0}},
    {"settings": {"booking_horizon_days": 9999}},
    {"settings": {"queue_policy": "RANDOM"}},
    {"settings": {"unknown_flag": True}},
    {"slug": "hijack"}, {"status": "ACTIVE"}, {"name": "x"},
])
def test_invalid_clinic_updates_rejected(env, body):
    assert patch(env.admin, env.base, body).status_code == 422


def test_only_admin_can_update_clinic(env):
    for c in (env.receptionist, env.doctor, env.patient):
        assert patch(c, env.base, {"name": "Hacked Name"}).status_code == 403


# ----------------------------------------------------------------- departments
def test_department_crud_and_validation(env):
    dept = mk_dept(env, "Cardiology", "cd")                       # prefix is normalised to upper-case
    listing = env.patient.get(f"{env.base}/departments").json()   # members of any role can read
    assert listing["total"] == 1 and listing["items"][0]["queue_prefix"] == "CD"

    assert post(env.admin, f"{env.base}/departments", {"name": "Cardiology", "queue_prefix": "X"}).status_code == 409
    assert post(env.admin, f"{env.base}/departments", {"name": "Other", "queue_prefix": "cd"}).status_code == 409
    for bad in ({"name": "A", "queue_prefix": "ABCD"}, {"name": "A", "queue_prefix": "A1"},
                {"name": "", "queue_prefix": "A"}, {"name": "A", "queue_prefix": "A", "clinic_id": str(uuid.uuid4())}):
        assert post(env.admin, f"{env.base}/departments", bad).status_code == 422

    assert patch(env.admin, f"{env.base}/departments/{dept}", {"name": "Heart Care"}).json()["name"] == "Heart Care"
    assert patch(env.admin, f"{env.base}/departments/{dept}", {"queue_prefix": "ZZ"}).status_code == 422  # immutable
    assert delete(env.admin, f"{env.base}/departments/{dept}").status_code == 204
    assert env.admin.get(f"{env.base}/departments").json()["total"] == 0


def test_department_write_requires_admin(env):
    for c in (env.receptionist, env.doctor, env.patient):
        assert post(c, f"{env.base}/departments", {"name": "Nope", "queue_prefix": "N"}).status_code == 403


def test_department_with_doctors_cannot_be_deleted(env):
    dept = mk_dept(env)
    mk_doctor(env, dept)
    assert delete(env.admin, f"{env.base}/departments/{dept}").status_code == 409


def test_department_pagination_is_bounded(env):
    for i, p in enumerate("ABC"):
        mk_dept(env, f"Dept {i}", p)
    page = env.admin.get(f"{env.base}/departments?limit=2&offset=0").json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert env.admin.get(f"{env.base}/departments?limit=100000").json()["limit"] == 100


# --------------------------------------------------------------------- doctors
def test_doctor_create_list_update(env):
    dept = mk_dept(env)
    doc = mk_doctor(env, dept, "Dr Alpha", default_slot_minutes=20, buffer_minutes=0)
    assert doc["status"] == "AVAILABLE" and doc["is_active"] and doc["has_account"] is False
    assert "user_id" not in doc and "email" not in str(doc).lower()

    r = patch(env.admin, f"{env.base}/doctors/{doc['id']}", {"display_name": "Dr Alpha Prime", "default_slot_minutes": 30})
    assert r.status_code == 200 and r.json()["default_slot_minutes"] == 30
    assert env.patient.get(f"{env.base}/doctors/{doc['id']}").json()["display_name"] == "Dr Alpha Prime"
    assert env.patient.get(f"{env.base}/doctors?department_id={dept}").json()["total"] == 1


@pytest.mark.parametrize("extra", [
    {"default_slot_minutes": 3}, {"default_slot_minutes": 500}, {"buffer_minutes": -1},
    {"display_name": "X"}, {"is_active": False}, {"status": "BUSY"},                  # not creatable
])
def test_invalid_doctor_payloads(env, extra):
    dept = mk_dept(env)
    r = post(env.admin, f"{env.base}/doctors", {"display_name": "Dr Valid", "department_id": dept, **extra})
    assert r.status_code == 422


def test_doctor_requires_existing_department_in_same_clinic(env):
    assert post(env.admin, f"{env.base}/doctors",
                {"display_name": "Dr Ghost", "department_id": str(uuid.uuid4())}).status_code == 404


def test_deactivated_doctor_hidden_from_patients_but_not_admin(env):
    dept = mk_dept(env)
    doc = mk_doctor(env, dept)
    assert patch(env.admin, f"{env.base}/doctors/{doc['id']}", {"is_active": False}).status_code == 200
    assert env.patient.get(f"{env.base}/doctors").json()["total"] == 0
    assert env.patient.get(f"{env.base}/doctors?include_inactive=true").json()["total"] == 0   # flag ignored for non-admins
    assert env.patient.get(f"{env.base}/doctors/{doc['id']}").status_code == 404
    assert env.admin.get(f"{env.base}/doctors").json()["total"] == 0
    assert env.admin.get(f"{env.base}/doctors?include_inactive=true").json()["total"] == 1
    assert env.admin.get(f"{env.base}/doctors/{doc['id']}").status_code == 200


def test_link_doctor_account_rules(env, owner_engine):
    dept = mk_dept(env)
    from sqlalchemy import text
    with owner_engine.connect() as c:
        doctor_uid = str(c.execute(text("select id from users where email=:e"),
                                   {"e": env.emails["DOCTOR"]}).scalar())
        patient_uid = str(c.execute(text("select id from users where email='patient-alpha@example.com'")).scalar())
    # a user who is not a DOCTOR member cannot be linked
    assert post(env.admin, f"{env.base}/doctors",
                {"display_name": "Dr Wrong", "department_id": dept, "user_id": patient_uid}).status_code == 422
    assert post(env.admin, f"{env.base}/doctors",
                {"display_name": "Dr Ghost", "department_id": dept, "user_id": str(uuid.uuid4())}).status_code == 422
    linked = mk_doctor(env, dept, "Dr Linked", user_id=doctor_uid)
    assert linked["has_account"] is True
    # one profile per account per clinic
    assert post(env.admin, f"{env.base}/doctors",
                {"display_name": "Dr Twin", "department_id": dept, "user_id": doctor_uid}).status_code == 409


# ----------------------------------------------------------------- doctor status
def _linked_doctor(env: Env, owner_engine, name="Dr Self") -> dict:
    from sqlalchemy import text
    dept = mk_dept(env, f"Dept-{name}", "S")
    with owner_engine.connect() as c:
        uid = str(c.execute(text("select id from users where email=:e"), {"e": env.emails["DOCTOR"]}).scalar())
    return mk_doctor(env, dept, name, user_id=uid)


def test_doctor_can_update_only_own_status(env, owner_engine):
    mine = _linked_doctor(env, owner_engine)
    other_dept = mk_dept(env, "Other", "O")
    other = mk_doctor(env, other_dept, "Dr Other")
    ok = post(env.doctor, f"{env.base}/doctors/{mine['id']}/status", {"status": "DELAYED", "current_delay_minutes": 15})
    assert ok.status_code == 200 and ok.json()["status"] == "DELAYED" and ok.json()["current_delay_minutes"] == 15
    assert post(env.doctor, f"{env.base}/doctors/{other['id']}/status", {"status": "BUSY"}).status_code == 403


def test_receptionist_and_admin_can_set_any_status_patient_cannot(env):
    dept = mk_dept(env)
    doc = mk_doctor(env, dept)
    url = f"{env.base}/doctors/{doc['id']}/status"
    assert post(env.receptionist, url, {"status": "BUSY"}).status_code == 200
    assert post(env.admin, url, {"status": "OFF_DUTY"}).json()["status"] == "OFF_DUTY"
    assert post(env.patient, url, {"status": "AVAILABLE"}).status_code == 403


@pytest.mark.parametrize("body", [
    {"status": "BUSY", "current_delay_minutes": 10},       # delay only valid with DELAYED
    {"status": "DELAYED", "current_delay_minutes": 9999},
    {"status": "SLEEPING"},
])
def test_invalid_status_updates(env, body):
    dept = mk_dept(env)
    doc = mk_doctor(env, dept)
    assert post(env.admin, f"{env.base}/doctors/{doc['id']}/status", body).status_code == 422


# ------------------------------------------------------------------- schedules
def test_schedule_create_list_delete_and_overlap(env):
    doc = mk_doctor(env, mk_dept(env))
    url = f"{env.base}/doctors/{doc['id']}/schedules"
    first = post(env.admin, url, {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00"})
    assert first.status_code == 201, first.text
    assert post(env.admin, url, {"day_of_week": 0, "start_time": "11:00", "end_time": "13:00"}).status_code == 409
    assert post(env.admin, url, {"day_of_week": 0, "start_time": "12:00", "end_time": "15:00"}).status_code == 201  # adjacent
    assert post(env.admin, url, {"day_of_week": 1, "start_time": "09:00", "end_time": "12:00"}).status_code == 201  # other day
    # same hours but a later validity window does not conflict with an open-ended-from-past window
    assert post(env.admin, url, {"day_of_week": 2, "start_time": "09:00", "end_time": "12:00",
                                 "valid_from": "2030-01-01", "valid_to": "2030-01-31"}).status_code == 201
    assert post(env.admin, url, {"day_of_week": 2, "start_time": "09:00", "end_time": "12:00",
                                 "valid_from": "2030-02-01"}).status_code == 201

    rows = env.patient.get(url).json()                       # patients may read schedules
    assert [(r["day_of_week"], r["start_time"]) for r in rows][:2] == [(0, "09:00:00"), (0, "12:00:00")]
    assert delete(env.admin, f"{url}/{first.json()['id']}").status_code == 204
    assert post(env.admin, url, {"day_of_week": 0, "start_time": "10:00", "end_time": "11:00"}).status_code == 201


@pytest.mark.parametrize("body", [
    {"day_of_week": 7, "start_time": "09:00", "end_time": "12:00"},
    {"day_of_week": -1, "start_time": "09:00", "end_time": "12:00"},
    {"day_of_week": 0, "start_time": "12:00", "end_time": "09:00"},
    {"day_of_week": 0, "start_time": "09:00", "end_time": "09:00"},
    {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00", "valid_from": "2030-02-01", "valid_to": "2030-01-01"},
    {"day_of_week": 0, "start_time": "09:00+06:00", "end_time": "12:00+06:00"},
    {"day_of_week": 0, "start_time": "nine", "end_time": "12:00"},
    {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00", "doctor_id": str(uuid.uuid4())},
])
def test_invalid_schedules(env, body):
    doc = mk_doctor(env, mk_dept(env))
    assert post(env.admin, f"{env.base}/doctors/{doc['id']}/schedules", body).status_code == 422


def test_schedule_write_requires_admin(env):
    doc = mk_doctor(env, mk_dept(env))
    url = f"{env.base}/doctors/{doc['id']}/schedules"
    for c in (env.receptionist, env.doctor, env.patient):
        assert post(c, url, {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00"}).status_code == 403


def test_schedule_id_from_other_doctor_is_404(env):
    dept = mk_dept(env)
    a, b = mk_doctor(env, dept, "Dr A"), mk_doctor(env, dept, "Dr B")
    sched = post(env.admin, f"{env.base}/doctors/{a['id']}/schedules",
                 {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00"}).json()
    assert delete(env.admin, f"{env.base}/doctors/{b['id']}/schedules/{sched['id']}").status_code == 404
    assert len(env.admin.get(f"{env.base}/doctors/{a['id']}/schedules").json()) == 1


# -------------------------------------------------------------------- time off
def test_time_off_lifecycle_and_access(env):
    doc = mk_doctor(env, mk_dept(env))
    url = f"{env.base}/doctors/{doc['id']}/time-off"
    body = {"starts_at": "2099-01-10T09:00:00+06:00", "ends_at": "2099-01-12T17:00:00+06:00", "reason": "Conference"}
    created = post(env.admin, url, body)
    assert created.status_code == 201, created.text
    assert created.json()["starts_at"].startswith("2099-01-10")
    for c in (env.admin, env.receptionist, env.doctor):          # staff can read
        assert len(c.get(url).json()) == 1
    assert env.patient.get(url).status_code == 403                # patients cannot see reasons
    assert post(env.receptionist, url, body).status_code == 403
    assert delete(env.admin, f"{url}/{created.json()['id']}").status_code == 204
    assert env.admin.get(url).json() == []


@pytest.mark.parametrize("body", [
    {"starts_at": "2099-01-12T09:00:00Z", "ends_at": "2099-01-10T09:00:00Z"},
    {"starts_at": "2099-01-10T09:00:00Z", "ends_at": "2099-01-10T09:00:00Z"},
    {"starts_at": "2099-01-10T09:00:00", "ends_at": "2099-01-11T09:00:00"},         # naive datetimes rejected
    {"starts_at": "2099-01-01T00:00:00Z", "ends_at": "2099-06-01T00:00:00Z"},       # > 90 days
    {"starts_at": "2099-01-10T09:00:00Z", "ends_at": "2099-01-11T09:00:00Z", "reason": "x" * 201},
])
def test_invalid_time_off(env, body):
    doc = mk_doctor(env, mk_dept(env))
    assert post(env.admin, f"{env.base}/doctors/{doc['id']}/time-off", body).status_code == 422


def test_past_time_off_hidden_by_upcoming_filter(env):
    doc = mk_doctor(env, mk_dept(env))
    url = f"{env.base}/doctors/{doc['id']}/time-off"
    post(env.admin, url, {"starts_at": "2020-01-10T09:00:00Z", "ends_at": "2020-01-11T09:00:00Z"})
    assert env.admin.get(url).json() == []
    assert len(env.admin.get(f"{url}?upcoming_only=false").json()) == 1


# --------------------------------------------------------------------- members
def test_member_deactivation_removes_access_immediately_and_is_reversible(env):
    members = env.admin.get(f"{env.base}/members").json()
    assert all("membership_id" in m for m in members)
    recep = next(m for m in members if m["role"] == "RECEPTIONIST")
    assert env.receptionist.get(f"{env.base}/departments").status_code == 200

    r = patch(env.admin, f"{env.base}/members/{recep['membership_id']}", {"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert env.receptionist.get(f"{env.base}/departments").status_code == 404     # no longer a member
    assert env.receptionist.get("/api/v1/auth/me").status_code == 200             # the account itself still works

    assert patch(env.admin, f"{env.base}/members/{recep['membership_id']}", {"is_active": True}).status_code == 200
    assert env.receptionist.get(f"{env.base}/departments").status_code == 200


def test_last_admin_cannot_be_deactivated(env):
    admin_membership = next(m for m in env.admin.get(f"{env.base}/members").json() if m["role"] == "CLINIC_ADMIN")
    r = patch(env.admin, f"{env.base}/members/{admin_membership['membership_id']}", {"is_active": False})
    assert r.status_code == 409
    assert env.admin.get(f"{env.base}/members").status_code == 200


def test_member_management_requires_admin_and_validates_input(env):
    members = env.admin.get(f"{env.base}/members").json()
    target = members[0]["membership_id"]
    for c in (env.receptionist, env.doctor, env.patient):
        assert patch(c, f"{env.base}/members/{target}", {"is_active": False}).status_code == 403
    assert patch(env.admin, f"{env.base}/members/{target}", {"role": "CLINIC_ADMIN"}).status_code == 422
    assert patch(env.admin, f"{env.base}/members/{target}", {"is_active": "maybe"}).status_code == 422


# --------------------------------------------------------- cross-tenant sweep
def test_other_clinics_ids_are_never_usable(owner_engine):
    a = setup_clinic(owner_engine, "alpha")
    b = setup_clinic(owner_engine, "beta")
    dept_a, dept_b = mk_dept(a, "Alpha Dept", "A"), mk_dept(b, "Beta Dept", "B")
    doc_a, _doc_b = mk_doctor(a, dept_a, "Dr Alpha"), mk_doctor(b, dept_b, "Dr Beta")
    sched_a = post(a.admin, f"{a.base}/doctors/{doc_a['id']}/schedules",
                   {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00"}).json()

    # B's admin works through A's clinic URL -> not a member -> 404 for everything.
    for method, path, body in [
        ("get", f"{a.base}/departments", None), ("post", f"{a.base}/departments", {"name": "X", "queue_prefix": "X"}),
        ("get", f"{a.base}/doctors", None), ("get", f"{a.base}/doctors/{doc_a['id']}", None),
        ("patch", f"{a.base}/doctors/{doc_a['id']}", {"display_name": "Pwned"}),
        ("get", f"{a.base}/doctors/{doc_a['id']}/schedules", None),
        ("delete", f"{a.base}/doctors/{doc_a['id']}/schedules/{sched_a['id']}", None),
    ]:
        r = getattr(b.admin, method)(path, **({} if method == "get" else {"headers": csrf(b.admin)}),
                                     **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, path, r.status_code)

    # B's admin using B's own URL but A's object ids -> also 404 (looked up inside B only).
    assert b.admin.get(f"{b.base}/doctors/{doc_a['id']}").status_code == 404
    assert patch(b.admin, f"{b.base}/doctors/{doc_a['id']}", {"display_name": "Pwned"}).status_code == 404
    assert b.admin.get(f"{b.base}/doctors/{doc_a['id']}/schedules").status_code == 404
    assert delete(b.admin, f"{b.base}/doctors/{doc_a['id']}/schedules/{sched_a['id']}").status_code == 404
    assert patch(b.admin, f"{b.base}/departments/{dept_a}", {"name": "Pwned"}).status_code == 404
    assert delete(b.admin, f"{b.base}/departments/{dept_a}").status_code == 404
    assert post(b.admin, f"{b.base}/doctors", {"display_name": "Dr Smuggle", "department_id": dept_a}).status_code == 404
    assert post(b.admin, f"{b.base}/doctors/{doc_a['id']}/status", {"status": "BUSY"}).status_code == 404

    a_member = a.admin.get(f"{a.base}/members").json()[0]["membership_id"]
    assert patch(b.admin, f"{b.base}/members/{a_member}", {"is_active": False}).status_code == 404

    # A's data is untouched.
    assert a.admin.get(f"{a.base}/doctors/{doc_a['id']}").json()["display_name"] == "Dr Alpha"
    assert {d["name"] for d in a.admin.get(f"{a.base}/departments").json()["items"]} == {"Alpha Dept"}
    assert {d["name"] for d in b.admin.get(f"{b.base}/departments").json()["items"]} == {"Beta Dept"}


def test_same_department_name_and_prefix_allowed_in_different_clinics(owner_engine):
    a, b = setup_clinic(owner_engine, "alpha"), setup_clinic(owner_engine, "beta")
    mk_dept(a, "General", "G")
    mk_dept(b, "General", "G")          # uniqueness is per clinic, not global


def test_mutations_are_audited(env, owner_engine):
    from sqlalchemy import text
    dept = mk_dept(env)
    doc = mk_doctor(env, dept)
    post(env.admin, f"{env.base}/doctors/{doc['id']}/status", {"status": "BUSY"})
    patch(env.admin, env.base, {"name": "Audited Name"})
    with owner_engine.connect() as c:
        actions = {r[0] for r in c.execute(text("select action from audit_logs where clinic_id=:c"), {"c": env.cid})}
    assert {"department.created", "doctor.created", "doctor.status_changed", "clinic.updated"} <= actions


def test_audit_log_is_tenant_scoped_for_clinic_context(owner_engine):
    """Audit rows written in clinic A are invisible to a session bound to clinic B (RLS)."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.core.database import get_engine, set_rls_context
    a, b = setup_clinic(owner_engine, "alpha"), setup_clinic(owner_engine, "beta")
    mk_dept(a)
    with Session(get_engine()) as db:
        set_rls_context(db, clinic_id=uuid.UUID(b.cid))
        rows = db.execute(text("select distinct clinic_id from audit_logs")).scalars().all()
    assert uuid.UUID(a.cid) not in rows
