from __future__ import annotations

import pytest

from tests.conftest import PASSWORD, csrf, login, new_client, register, reset_token_from_outbox, signup


def test_register_login_me(client):
    r = register(client, "Alice@example.com")
    assert r.status_code == 201
    body = r.json()
    assert body["email"].lower() == "alice@example.com"
    assert "password" not in str(body).lower() and "hash" not in str(body).lower()

    r = login(client, "alice@example.com")
    assert r.status_code == 200 and r.json()["csrf_token"]
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "alice@example.com"
    assert me.json()["memberships"] == []


def test_auth_cookies_are_httponly_and_scoped(client):
    register(client, "a@example.com")
    r = login(client, "a@example.com")
    cookies = {h.split("=", 1)[0]: h.lower() for h in r.headers.get_list("set-cookie")}
    assert "httponly" in cookies["qc_access"] and "samesite=lax" in cookies["qc_access"]
    assert "httponly" in cookies["qc_refresh"] and "path=/api/v1/auth" in cookies["qc_refresh"]
    assert "httponly" not in cookies["qc_csrf"]  # must be readable for double-submit
    assert "access_token" not in r.text  # tokens are never in the JSON body


def test_duplicate_registration_is_conflict_without_detail(client):
    assert register(client, "dup@example.com").status_code == 201
    r = register(client, "DUP@example.com")
    assert r.status_code == 409
    assert "exists" not in r.text.lower()


@pytest.mark.parametrize("pw", ["short", "password12345", "x" * 11])
def test_weak_passwords_rejected_without_echo(client, pw):
    r = register(client, "weak@example.com", password=pw)
    assert r.status_code == 422
    assert pw not in r.text or len(pw) < 6


def test_mass_assignment_blocked(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "evil@example.com", "password": PASSWORD, "full_name": "Evil",
        "platform_role": "SUPER_ADMIN", "is_active": True, "email_verified": True})
    assert r.status_code == 422


def test_wrong_password_and_unknown_user_look_identical(client):
    register(client, "real@example.com")
    a = login(client, "real@example.com", "Wrong-Password-123")
    b = login(client, "ghost@example.com", "Wrong-Password-123")
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_lockout_after_repeated_failures_even_with_correct_password(client):
    register(client, "lock@example.com")
    for _ in range(5):
        assert login(client, "lock@example.com", "Wrong-Password-123").status_code == 401
    r = login(client, "lock@example.com", PASSWORD)   # correct, but account is locked
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Invalid email or password."


def test_login_rate_limited_per_ip(client):
    codes = [login(client, "nobody@example.com", "Wrong-Password-123").status_code for _ in range(22)]
    assert 429 in codes
    assert codes[0] == 401


def test_refresh_rotates_and_old_token_is_dead_and_triggers_revocation(client):
    signup(client, "r@example.com")
    old_refresh = client.cookies.get("qc_refresh")
    assert client.post("/api/v1/auth/refresh", headers=csrf(client)).status_code == 200
    new_refresh = client.cookies.get("qc_refresh")
    assert new_refresh and new_refresh != old_refresh
    assert client.get("/api/v1/auth/me").status_code == 200

    # Replay the rotated-out token (attacker scenario) -> rejected AND the whole session is revoked.
    headers = csrf(client)
    client.cookies.delete("qc_refresh", path="/api/v1/auth")
    client.cookies.set("qc_refresh", old_refresh, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=headers).status_code == 401
    # The legitimate (newest) refresh token no longer works either: the session is dead.
    # (A valid CSRF pair is supplied so a 401 can only come from the revoked session.)
    client.cookies.clear()
    client.cookies.set("qc_refresh", new_refresh, path="/api/v1/auth")
    client.cookies.set("qc_csrf", headers["X-CSRF-Token"], path="/")
    assert client.post("/api/v1/auth/refresh", headers=headers).status_code == 401


def test_refresh_requires_csrf_header(client):
    signup(client, "c@example.com")
    assert client.post("/api/v1/auth/refresh").status_code == 403


def test_logout_revokes_session_server_side(client):
    signup(client, "out@example.com")
    stolen_access = client.cookies.get("qc_access")
    assert client.post("/api/v1/auth/logout", headers=csrf(client)).status_code == 204
    other = new_client()
    r = other.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {stolen_access}"})
    assert r.status_code == 401  # JWT still unexpired, but its session is revoked


def test_logout_requires_csrf(client):
    signup(client, "csrf@example.com")
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_logout_all_kills_every_session(client):
    signup(client, "multi@example.com")
    second = new_client()
    assert login(second, "multi@example.com").status_code == 200
    assert client.post("/api/v1/auth/logout-all", headers=csrf(client)).status_code == 204
    assert second.get("/api/v1/auth/me").status_code == 401


def test_sessions_list_and_cannot_revoke_someone_elses_session(client):
    signup(client, "s1@example.com")
    mine = client.get("/api/v1/auth/sessions").json()
    assert len(mine) == 1 and mine[0]["current"] is True

    victim = new_client()
    signup(victim, "s2@example.com")
    victim_session = victim.get("/api/v1/auth/sessions").json()[0]["id"]
    r = client.delete(f"/api/v1/auth/sessions/{victim_session}", headers=csrf(client))
    assert r.status_code == 404                                  # IDOR attempt
    assert victim.get("/api/v1/auth/me").status_code == 200       # victim unaffected


def test_password_reset_flow_single_use_and_revokes_sessions(client):
    signup(client, "reset@example.com")
    anon = new_client()
    r = anon.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"})
    assert r.status_code == 202
    token = reset_token_from_outbox("password_reset")

    new_pw = "Brand-New-Passphrase-42"
    assert anon.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new_pw}).status_code == 204
    # old session is dead, old password dead, new password works
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(anon, "reset@example.com", PASSWORD).status_code == 401
    assert login(anon, "reset@example.com", new_pw).status_code == 200
    # token cannot be reused
    assert anon.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new_pw + "x"}).status_code == 400


def test_forgot_password_does_not_enumerate(client):
    register(client, "known@example.com")
    a = client.post("/api/v1/auth/forgot-password", json={"email": "known@example.com"})
    b = client.post("/api/v1/auth/forgot-password", json={"email": "unknown@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()


def test_reset_with_garbage_token_fails(client):
    r = client.post("/api/v1/auth/reset-password", json={"token": "x" * 30, "new_password": "Brand-New-Passphrase-42"})
    assert r.status_code == 400


def test_email_verification(client):
    register(client, "verify@example.com")
    token = reset_token_from_outbox("email_verify")
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 204
    login(client, "verify@example.com")
    assert client.get("/api/v1/auth/me").json()["user"]["email_verified"] is True
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400


def test_audit_trail_written_for_auth_events(client, owner_engine):
    from sqlalchemy import text
    register(client, "audit@example.com")
    login(client, "audit@example.com", "Wrong-Password-123")
    login(client, "audit@example.com")
    with owner_engine.connect() as c:
        actions = {r[0] for r in c.execute(text("select action from audit_logs"))}
    assert {"auth.register", "auth.login_failed", "auth.login"} <= actions
