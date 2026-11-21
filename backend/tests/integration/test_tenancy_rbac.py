"""Multi-tenancy, RBAC, privilege escalation and IDOR tests through the real API."""
from __future__ import annotations

import uuid

from tests.conftest import (
    create_active_clinic, csrf, login, make_superadmin, new_client, signup,
)


def _two_clinics(owner_engine):
    admin_a, admin_b = new_client(), new_client()
    signup(admin_a, "admin-a@example.com")
    signup(admin_b, "admin-b@example.com")
    clinic_a = create_active_clinic(owner_engine, admin_a, "clinic-alpha", "Alpha")
    clinic_b = create_active_clinic(owner_engine, admin_b, "clinic-beta", "Beta")
    return admin_a, admin_b, clinic_a, clinic_b


def test_clinic_registration_starts_pending_and_creator_is_admin(client, owner_engine):
    signup(client, "founder@example.com")
    r = client.post("/api/v1/clinics", json={"name": "New Clinic", "slug": "new-clinic"}, headers=csrf(client))
    assert r.status_code == 201 and r.json()["status"] == "PENDING"
    cid = r.json()["id"]
    assert client.get(f"/api/v1/clinics/{cid}").status_code == 200       # may view own pending clinic
    assert client.get(f"/api/v1/clinics/{cid}/members").status_code == 403  # but it is not active yet
    assert client.get("/api/v1/clinics").json()["total"] == 0              # not in public directory
    me = client.get("/api/v1/auth/me").json()
    assert me["memberships"] == [{"clinic_id": cid, "role": "CLINIC_ADMIN"}]


def test_duplicate_slug_conflict(client):
    signup(client, "s@example.com")
    assert client.post("/api/v1/clinics", json={"name": "One", "slug": "same-slug"}, headers=csrf(client)).status_code == 201
    assert client.post("/api/v1/clinics", json={"name": "Two", "slug": "SAME-slug"}, headers=csrf(client)).status_code == 409


def test_cross_tenant_access_is_blocked_with_404(owner_engine):
    admin_a, admin_b, clinic_a, clinic_b = _two_clinics(owner_engine)
    # Each admin can use their own clinic...
    assert admin_a.get(f"/api/v1/clinics/{clinic_a}/members").status_code == 200
    # ...but any attempt on the other tenant looks like "does not exist".
    for path in (f"/api/v1/clinics/{clinic_b}", f"/api/v1/clinics/{clinic_b}/members"):
        assert admin_a.get(path).status_code == 404, path
        assert admin_b.get(path.replace(clinic_b, clinic_a)).status_code == 404
    r = admin_a.post(f"/api/v1/clinics/{clinic_b}/members", json={"email": "admin-a@example.com", "role": "CLINIC_ADMIN"},
                     headers=csrf(admin_a))
    assert r.status_code == 404
    # 404 for a random id looks identical to a real-but-forbidden clinic (no existence oracle).
    ghost = admin_a.get(f"/api/v1/clinics/{uuid.uuid4()}")
    real_other = admin_a.get(f"/api/v1/clinics/{clinic_b}")
    assert ghost.status_code == real_other.status_code == 404
    assert ghost.json()["error"]["message"] == real_other.json()["error"]["message"]


def test_member_lists_do_not_leak_across_tenants(owner_engine):
    admin_a, admin_b, clinic_a, clinic_b = _two_clinics(owner_engine)
    emails_a = {m["email"] for m in admin_a.get(f"/api/v1/clinics/{clinic_a}/members").json()}
    emails_b = {m["email"] for m in admin_b.get(f"/api/v1/clinics/{clinic_b}/members").json()}
    assert emails_a == {"admin-a@example.com"} and emails_b == {"admin-b@example.com"}


def test_patient_self_join_grants_patient_role_only(owner_engine):
    admin_a, _, clinic_a, _ = _two_clinics(owner_engine)
    patient = new_client()
    signup(patient, "patient@example.com")
    assert patient.post(f"/api/v1/clinics/{clinic_a}/join", headers=csrf(patient)).status_code == 204
    assert patient.post(f"/api/v1/clinics/{clinic_a}/join", headers=csrf(patient)).status_code == 204  # idempotent
    roles = patient.get("/api/v1/auth/me").json()["memberships"]
    assert roles == [{"clinic_id": clinic_a, "role": "PATIENT"}]


def test_privilege_escalation_attempts_fail(owner_engine):
    admin_a, _, clinic_a, _ = _two_clinics(owner_engine)
    patient = new_client()
    signup(patient, "pat@example.com")
    patient.post(f"/api/v1/clinics/{clinic_a}/join", headers=csrf(patient))

    # patient cannot list or add staff
    assert patient.get(f"/api/v1/clinics/{clinic_a}/members").status_code == 403
    r = patient.post(f"/api/v1/clinics/{clinic_a}/members", json={"email": "pat@example.com", "role": "CLINIC_ADMIN"},
                     headers=csrf(patient))
    assert r.status_code == 403
    # join cannot be abused to pick a role
    r = patient.post(f"/api/v1/clinics/{clinic_a}/join", json={"role": "CLINIC_ADMIN"}, headers=csrf(patient))
    assert patient.get("/api/v1/auth/me").json()["memberships"] == [{"clinic_id": clinic_a, "role": "PATIENT"}]
    # nobody but a super admin reaches platform endpoints (clinic admins included)
    for c in (patient, admin_a):
        assert c.get("/api/v1/platform/clinics").status_code == 403
        assert c.get("/api/v1/platform/audit-logs").status_code == 403
        r = c.post(f"/api/v1/platform/clinics/{clinic_a}/status", json={"status": "SUSPENDED"}, headers=csrf(c))
        assert r.status_code == 403


def test_clinic_admin_can_add_staff_with_role_and_audit(owner_engine):
    admin_a, _, clinic_a, _ = _two_clinics(owner_engine)
    staff = new_client()
    signup(staff, "recep@example.com")
    r = admin_a.post(f"/api/v1/clinics/{clinic_a}/members", json={"email": "recep@example.com", "role": "RECEPTIONIST"},
                     headers=csrf(admin_a))
    assert r.status_code == 201 and r.json()["role"] == "RECEPTIONIST"
    assert admin_a.post(f"/api/v1/clinics/{clinic_a}/members", json={"email": "recep@example.com", "role": "RECEPTIONIST"},
                        headers=csrf(admin_a)).status_code == 409
    # receptionist now belongs but may not manage staff
    assert staff.get(f"/api/v1/clinics/{clinic_a}/members").status_code == 403
    assert staff.get(f"/api/v1/clinics/{clinic_a}").status_code == 200
    # the staff member has no access to the other clinic
    assert staff.get(f"/api/v1/clinics/{uuid.uuid4()}").status_code == 404


def test_unknown_role_and_extra_fields_rejected(owner_engine):
    admin_a, _, clinic_a, _ = _two_clinics(owner_engine)
    for body in ({"email": "x@example.com", "role": "SUPER_ADMIN"}, {"email": "x@example.com", "role": "ROOT"},
                 {"email": "x@example.com", "role": "DOCTOR", "clinic_id": str(uuid.uuid4())}):
        assert admin_a.post(f"/api/v1/clinics/{clinic_a}/members", json=body, headers=csrf(admin_a)).status_code == 422


def test_super_admin_has_no_implicit_clinic_access_but_can_use_platform_routes(owner_engine):
    _, _, clinic_a, _ = _two_clinics(owner_engine)
    email = make_superadmin(owner_engine, "boss@example.com")
    root = new_client()
    assert login(root, email).status_code == 200
    assert root.get(f"/api/v1/clinics/{clinic_a}/members").status_code == 404   # tenant routes need membership
    listing = root.get("/api/v1/platform/clinics")
    assert listing.status_code == 200 and {c["slug"] for c in listing.json()} >= {"clinic-alpha", "clinic-beta"}
    r = root.post(f"/api/v1/platform/clinics/{clinic_a}/status", json={"status": "SUSPENDED"}, headers=csrf(root))
    assert r.status_code == 200 and r.json()["status"] == "SUSPENDED"
    actions = [a["action"] for a in root.get("/api/v1/platform/audit-logs").json()]
    assert "platform.clinic_status_changed" in actions


def test_suspended_clinic_is_locked_out(owner_engine):
    admin_a, _, clinic_a, _ = _two_clinics(owner_engine)
    root = new_client()
    login(root, make_superadmin(owner_engine, "boss2@example.com"))
    root.post(f"/api/v1/platform/clinics/{clinic_a}/status", json={"status": "SUSPENDED"}, headers=csrf(root))
    assert admin_a.get(f"/api/v1/clinics/{clinic_a}/members").status_code == 403
    patient = new_client()
    signup(patient, "late@example.com")
    assert patient.post(f"/api/v1/clinics/{clinic_a}/join", headers=csrf(patient)).status_code == 404
    assert {c["slug"] for c in admin_a.get("/api/v1/clinics").json()["items"]} == {"clinic-beta"}


def test_invalid_status_value_rejected(owner_engine):
    _, _, clinic_a, _ = _two_clinics(owner_engine)
    root = new_client()
    login(root, make_superadmin(owner_engine, "boss3@example.com"))
    assert root.post(f"/api/v1/platform/clinics/{clinic_a}/status", json={"status": "DELETED"}, headers=csrf(root)).status_code == 422


def test_deactivated_membership_loses_access(owner_engine):
    from sqlalchemy import text
    admin_a, _, clinic_a, _ = _two_clinics(owner_engine)
    assert admin_a.get(f"/api/v1/clinics/{clinic_a}/members").status_code == 200
    with owner_engine.begin() as c:
        c.execute(text("update clinic_memberships set is_active=false"))
    assert admin_a.get(f"/api/v1/clinics/{clinic_a}/members").status_code == 404


def _directory(client, **params):
    r = client.get("/api/v1/clinics", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _names(client, **params) -> list[str]:
    return [c["name"] for c in _directory(client, **params)["items"]]


def _search_clinics(owner_engine):
    """Five approved clinics, one signed-in admin. Names and addresses (slugs) are chosen so each test has one right answer."""
    admin = new_client()
    signup(admin, "searcher@example.com")
    for slug, name in [("city-dental", "City Dental Care"), ("north-clinic", "North Family Clinic"),
                       ("dental-hub", "Hub Dentistry"), ("odd-100", "Fifty% Off_Clinic"), ("quiet", "Quiet Pending")]:
        create_active_clinic(owner_engine, admin, slug, name)
    return admin


def test_directory_without_a_search_lists_everything_by_name(owner_engine):
    admin = _search_clinics(owner_engine)
    assert _names(admin) == ["City Dental Care", "Fifty% Off_Clinic", "Hub Dentistry", "North Family Clinic", "Quiet Pending"]
    assert _names(admin, q="") == _names(admin) and _names(admin, q="   ") == _names(admin)


def test_directory_search_matches_every_word_in_name_or_address(owner_engine):
    admin = _search_clinics(owner_engine)
    assert _names(admin, q="dental") == ["City Dental Care", "Hub Dentistry"]   # the second matches by its address, dental-hub
    assert _names(admin, q="CITY") == ["City Dental Care"]                       # ignores case
    assert _names(admin, q="  city   care ") == ["City Dental Care"]             # every word must match; extra spaces are ignored
    assert _names(admin, q="city north") == []
    assert _names(admin, q="family") == ["North Family Clinic"]
    assert _names(admin, q="north-clinic") == ["North Family Clinic"]            # the address is searched as well
    result = _directory(admin, q="zzzz")
    assert result["items"] == [] and result["total"] == 0


def test_directory_search_puts_names_starting_with_the_word_first(owner_engine):
    admin = _search_clinics(owner_engine)
    # Every clinic has an "n" somewhere. "North ..." starts with it, so it leads; the rest stay in name order.
    assert _names(admin, q="n") == ["North Family Clinic", "City Dental Care", "Fifty% Off_Clinic", "Hub Dentistry", "Quiet Pending"]


def test_directory_search_treats_wildcards_as_text(owner_engine):
    admin = _search_clinics(owner_engine)
    assert _names(admin, q="%") == ["Fifty% Off_Clinic"]
    assert _names(admin, q="_") == ["Fifty% Off_Clinic"]
    assert _directory(admin, q="\\")["total"] == 0
    assert _directory(admin, q="c_ty")["total"] == 0                            # "_" is not "any one character"


def test_directory_search_pages_and_stays_bounded(owner_engine):
    admin = _search_clinics(owner_engine)
    first = _directory(admin, q="clinic", limit=1)
    assert first["total"] == 2 and len(first["items"]) == 1
    second = _directory(admin, q="clinic", limit=1, offset=1)
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert admin.get("/api/v1/clinics", params={"q": "x" * 101}).status_code == 422
    assert _directory(admin, q=" ".join(["clinic"] * 14))["total"] == 2          # only the first five words count; 14 is not an error


def test_directory_search_never_shows_unapproved_clinics(owner_engine):
    admin = _search_clinics(owner_engine)
    r = admin.post("/api/v1/clinics", json={"name": "Hidden Waiting Clinic", "slug": "hidden-waiting"}, headers=csrf(admin))
    assert r.status_code == 201
    assert _directory(admin, q="hidden")["total"] == 0
    assert _directory(admin, q="waiting")["total"] == 0
    assert _directory(admin, q="clinic")["total"] == 2                           # still only the approved ones


def test_directory_pagination_is_bounded(owner_engine):
    admin_a, _, _, _ = _two_clinics(owner_engine)
    page = admin_a.get("/api/v1/clinics?limit=1&offset=0").json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert admin_a.get("/api/v1/clinics?limit=100000").json()["limit"] == 100
