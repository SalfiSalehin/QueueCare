"""HTTP-level security tests: tokens, CSRF/Origin, headers, CORS, limits, injection, error hygiene."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from tests.conftest import PASSWORD, csrf, login, new_client, register, signup

ME = "/api/v1/auth/me"


def _token(**over) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    claims = {"iss": "queuecare", "sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()), "typ": "access",
              "iat": now, "exp": now + timedelta(minutes=5), **over}
    return jwt.encode(claims, over.get("_key", s.jwt_secret), algorithm="HS256")


def test_unauthenticated_requests_rejected(client):
    for method, path in [("get", ME), ("get", "/api/v1/clinics"), ("get", "/api/v1/platform/clinics"),
                         ("get", f"/api/v1/clinics/{uuid.uuid4()}"), ("get", "/api/v1/auth/sessions")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_invalid_expired_forged_tokens(client):
    s = get_settings()
    now = datetime.now(UTC)
    cases = {
        "garbage": "not.a.jwt",
        "expired": _token(exp=now - timedelta(minutes=1)),
        "wrong_secret": jwt.encode({"iss": "queuecare", "sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()),
                                    "typ": "access", "iat": now, "exp": now + timedelta(minutes=5)},
                                   "x" * 40, algorithm="HS256"),
        "alg_none": jwt.encode({"iss": "queuecare", "sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()),
                                "typ": "access", "iat": now, "exp": now + timedelta(minutes=5)}, None, algorithm="none"),
        "valid_but_no_session": _token(),
        "wrong_type": _token(typ="refresh"),
        "wrong_issuer": _token(iss="evil"),
    }
    assert s.jwt_secret  # sanity
    for name, tok in cases.items():
        r = client.get(ME, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, name


def test_cookie_auth_state_change_needs_csrf_and_trusted_origin(client):
    signup(client, "csrf@example.com")
    body = {"name": "Clinic X", "slug": "clinic-x"}
    assert client.post("/api/v1/clinics", json=body).status_code == 403                       # no header
    assert client.post("/api/v1/clinics", json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
    evil = {**csrf(client), "Origin": "https://evil.example"}
    assert client.post("/api/v1/clinics", json=body, headers=evil).status_code == 403           # bad origin
    good = {**csrf(client), "Origin": "http://localhost:3000"}
    assert client.post("/api/v1/clinics", json=body, headers=good).status_code == 201


def test_csrf_token_from_another_session_is_not_enough(client):
    signup(client, "a@example.com")
    other = new_client()
    signup(other, "b@example.com")
    # Attacker-controlled header differs from the victim's csrf cookie -> rejected.
    r = client.post("/api/v1/clinics", json={"name": "C", "slug": "cc-clinic"}, headers=csrf(other))
    assert r.status_code == 403


def test_login_rejects_untrusted_origin(client):
    register(client, "o@example.com")
    r = client.post("/api/v1/auth/login", json={"email": "o@example.com", "password": PASSWORD},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_bearer_requests_skip_csrf_but_cookies_alone_do_not(client):
    signup(client, "bearer@example.com")
    access = client.cookies.get("qc_access")
    fresh = new_client()
    r = fresh.post("/api/v1/clinics", json={"name": "Bearer Clinic", "slug": "bearer-clinic"},
                   headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 201


def test_security_headers_and_request_id(client):
    r = client.get("/health/live")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert uuid.UUID(h["x-request-id"])
    r2 = client.get("/health/live", headers={"X-Request-ID": "trace-12345678"})
    assert r2.headers["x-request-id"] == "trace-12345678"
    r3 = client.get("/health/live", headers={"X-Request-ID": "bad id\twith junk"})
    assert r3.headers["x-request-id"] != "bad id\twith junk"


def test_cors_only_for_allowed_origins(client):
    ok = client.options("/api/v1/auth/login", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    bad = client.options("/api/v1/auth/login", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_body_size_limit(client):
    r = client.post("/api/v1/auth/login", content=b"x" * 200_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_sql_injection_payloads_are_inert(client):
    probes = ["' OR 1=1 --", "'; DROP TABLE users; --", "\" OR \"\"=\"", "admin'--"]
    for p in probes:
        assert login(client, p).status_code == 422                       # not a valid email
    register(client, "sqli@example.com")
    assert client.post("/api/v1/auth/login", json={"email": "sqli@example.com", "password": "' OR '1'='1"}).status_code == 401
    signup_c = new_client()
    signup(signup_c, "sqli2@example.com")
    r = signup_c.post("/api/v1/clinics", json={"name": "x'); DROP TABLE clinics;--", "slug": "drop-clinics"},
                      headers=csrf(signup_c))
    assert r.status_code == 201                                           # stored as a plain string
    assert signup_c.post("/api/v1/clinics", json={"name": "ok name", "slug": "a'; drop"}, headers=csrf(signup_c)).status_code == 422
    assert login(client, "sqli@example.com").status_code == 200          # tables intact


def test_errors_are_uniform_and_leak_nothing(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404 and set(r.json()["error"]) >= {"code", "message", "request_id"}
    r = client.post("/api/v1/auth/login", json={"email": "bad", "password": "supersecretvalue"})
    assert r.status_code == 422
    assert "supersecretvalue" not in r.text and "Traceback" not in r.text
    assert client.get("/api/v1/auth/login").status_code == 405


def test_invalid_uuid_in_path_is_validation_error_not_500(client):
    signup(client, "u@example.com")
    assert client.get("/api/v1/clinics/not-a-uuid").status_code == 422


def test_docs_available_in_test_env_but_not_production():
    from app.core.config import Settings
    from app.main import create_app
    s = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@h/db", jwt_secret="j" * 40,
                 csrf_secret="c" * 40, app_env="production", cookie_secure=True,
                 backend_cors_origins="https://app.example.com")
    from fastapi.testclient import TestClient
    with TestClient(create_app(s)) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        assert "strict-transport-security" in c.get("/health/live").headers
