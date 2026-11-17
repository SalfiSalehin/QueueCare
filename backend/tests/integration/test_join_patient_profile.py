"""Joining a clinic creates the person's patient profile there (so reception can find them and their own queue
screen shows their tokens). Idempotent, per clinic, and never reachable across clinics. SYNTHETIC data only."""
from __future__ import annotations

from sqlalchemy import text

from tests.conftest import create_active_clinic, csrf, login, new_client, register, signup


def _clinic_with_receptionist(owner_engine, slug: str):
    admin = new_client()
    signup(admin, f"admin-{slug}@example.com")
    cid = create_active_clinic(owner_engine, admin, f"clinic-{slug}", f"Clinic {slug}")
    recep = new_client()
    signup(recep, f"recep-{slug}@example.com")
    r = admin.post(f"/api/v1/clinics/{cid}/members", json={"email": f"recep-{slug}@example.com",
                                                           "role": "RECEPTIONIST"}, headers=csrf(admin))
    assert r.status_code == 201, r.text
    return admin, recep, cid


def _person(email: str, name: str):
    c = new_client()
    assert register(c, email, name=name).status_code == 201
    assert login(c, email).status_code == 200
    return c


def _count(owner_engine, cid: str, email: str) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM patients p JOIN users u ON u.id = p.user_id "
            "WHERE p.clinic_id = :c AND u.email = :e AND p.deleted_at IS NULL"), {"c": cid, "e": email}).scalar_one()


def test_join_creates_a_findable_linked_patient_profile(owner_engine):
    _, recep, cid = _clinic_with_receptionist(owner_engine, "jp1")
    person = _person("zoe-joiner@example.com", "Zoe Joiner Synthetic")
    assert person.post(f"/api/v1/clinics/{cid}/join", headers=csrf(person)).status_code == 204
    found = recep.get(f"/api/v1/clinics/{cid}/patients", params={"q": "zoe joiner"}).json()
    assert found["total"] == 1
    item = found["items"][0]
    assert item["full_name"] == "Zoe Joiner Synthetic" and item["has_account"] is True
    assert _count(owner_engine, cid, "zoe-joiner@example.com") == 1


def test_join_is_idempotent_and_never_duplicates_the_profile(owner_engine):
    _, _, cid = _clinic_with_receptionist(owner_engine, "jp2")
    person = _person("ivy-twice@example.com", "Ivy Twice Synthetic")
    for _ in range(3):
        assert person.post(f"/api/v1/clinics/{cid}/join", headers=csrf(person)).status_code == 204
    assert _count(owner_engine, cid, "ivy-twice@example.com") == 1
    with owner_engine.connect() as conn:
        memberships = conn.execute(text(
            "SELECT count(*) FROM clinic_memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.clinic_id = :c AND u.email = 'ivy-twice@example.com' AND m.role = 'PATIENT'"),
            {"c": cid}).scalar_one()
    assert memberships == 1


def test_profile_is_per_clinic_and_invisible_to_the_other_clinic(owner_engine):
    _, recep_a, cid_a = _clinic_with_receptionist(owner_engine, "jpa")
    _, recep_b, cid_b = _clinic_with_receptionist(owner_engine, "jpb")
    person = _person("max-both@example.com", "Max Both Synthetic")
    assert person.post(f"/api/v1/clinics/{cid_a}/join", headers=csrf(person)).status_code == 204
    assert recep_a.get(f"/api/v1/clinics/{cid_a}/patients", params={"q": "max both"}).json()["total"] == 1
    assert recep_b.get(f"/api/v1/clinics/{cid_b}/patients", params={"q": "max both"}).json()["total"] == 0
    assert recep_b.get(f"/api/v1/clinics/{cid_a}/patients", params={"q": "max both"}).status_code == 404
    assert person.post(f"/api/v1/clinics/{cid_b}/join", headers=csrf(person)).status_code == 204
    assert _count(owner_engine, cid_a, "max-both@example.com") == 1
    assert _count(owner_engine, cid_b, "max-both@example.com") == 1
    assert recep_b.get(f"/api/v1/clinics/{cid_b}/patients", params={"q": "max both"}).json()["total"] == 1


def test_join_still_refuses_an_inactive_clinic_and_creates_nothing(owner_engine):
    admin = new_client()
    signup(admin, "admin-pending@example.com")
    r = admin.post("/api/v1/clinics", json={"name": "Pending Clinic", "slug": "pending-jp"}, headers=csrf(admin))
    cid = r.json()["id"]  # PENDING: not approved
    person = _person("pat-pending@example.com", "Pat Pending Synthetic")
    assert person.post(f"/api/v1/clinics/{cid}/join", headers=csrf(person)).status_code == 404
    assert _count(owner_engine, cid, "pat-pending@example.com") == 0


def test_joined_patient_can_book_and_sees_the_same_single_profile(owner_engine):
    """Booking after joining reuses the profile created at join (no second row)."""
    from tests.integration.test_appointments import book, setup_bookable, slots
    b = setup_bookable(owner_engine, slug="jpbook")
    email = "patient-jpbook@example.com"
    assert _count(owner_engine, b.env.cid, email) == 1      # created by the join inside setup_clinic
    assert book(b, slots(b)[0]["starts_at"]).status_code == 201
    assert _count(owner_engine, b.env.cid, email) == 1
