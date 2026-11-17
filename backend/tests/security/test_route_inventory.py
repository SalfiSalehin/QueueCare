"""Route inventory: every API route is accounted for, so a newly added route cannot ship unprotected by accident.

* Anonymous callers get 401/403 from every route except an explicit public allowlist.
* A signed-in user who is NOT a member of a clinic gets 404 (not 403, not data) from every clinic-scoped route.
"""
from __future__ import annotations

import re
import uuid

import pytest

from app.core.config import get_settings
from app.main import create_app
from tests.conftest import new_client, signup
from tests.integration.test_appointments import setup_bookable

# (method, path) pairs that are intentionally reachable without a session. Adding to this list is a security decision.
PUBLIC = {
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/refresh"),       # authenticated by the refresh cookie, 401 without it (checked below)
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    # Interactive API docs: served only outside production (test_docs_available_in_test_env_but_not_production).
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/openapi.json"),
}
# Clinic-scoped routes where any signed-in user (not only members) is allowed by design.
OPEN_TO_ANY_USER = {("POST", "/api/v1/clinics/{clinic_id}/join"), ("GET", "/api/v1/clinics"), ("POST", "/api/v1/clinics")}
FIXED = {"action": "call"}


HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _walk(routes, prefix=""):
    """Duck-typed walk of the router tree (route classes differ between FastAPI/Starlette versions)."""
    for r in routes:
        path = prefix + getattr(r, "path", "")
        methods = getattr(r, "methods", None)
        if methods and getattr(r, "endpoint", None) is not None and "websocket" not in type(r).__name__.lower():
            for m in sorted(set(methods) & HTTP_METHODS):
                yield m, path
        inner = getattr(r, "routes", None) or getattr(getattr(r, "router", None), "routes", None)
        if inner:
            yield from _walk(inner, path)


def all_routes():
    """HTTP operations as (METHOD, path), from the router tree and the OpenAPI schema (their union).
    WebSockets are covered by tests/integration/test_realtime.py."""
    app = create_app(get_settings())
    found = set(_walk(app.routes))
    for path, item in app.openapi()["paths"].items():
        found |= {(m.upper(), path) for m in item if m.upper() in HTTP_METHODS}
    kinds = sorted({type(r).__name__ for r in app.routes})
    assert len(found) > 60, f"route enumeration found only {len(found)} routes (app.routes types: {kinds})"
    return found


def routes(app):  # kept for readability at call sites that already hold an app
    return _walk(app.routes)


def fill(path: str, **over: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: over.get(m.group(1)) or FIXED.get(m.group(1)) or str(uuid.uuid4()), path)


def call(c, method: str, url: str):
    return c.request(method, url, json={} if method in {"POST", "PUT", "PATCH"} else None)


def test_inventory_is_not_empty_and_public_list_is_accurate(client):
    found = all_routes()
    assert PUBLIC - found == set(), "PUBLIC lists a route that no longer exists"


def test_every_non_public_route_rejects_anonymous_callers(client):
    leaks = []
    for method, path in sorted(all_routes()):
        if (method, path) in PUBLIC:
            continue
        status = call(new_client(), method, fill(path)).status_code
        if status not in (401, 403):
            leaks.append((method, path, status))
    assert leaks == [], f"routes that answered an anonymous request: {leaks}"


def test_refresh_needs_its_cookie(client):
    assert client.post("/api/v1/auth/refresh").status_code in (401, 403)


def test_every_clinic_scoped_route_hides_the_clinic_from_non_members(client, owner_engine):
    b = setup_bookable(owner_engine, slug="alpha")
    stranger = new_client()
    signup(stranger, "stranger@example.com")
    leaks = []
    for method, path in sorted(all_routes()):
        if "{clinic_id}" not in path or (method, path) in OPEN_TO_ANY_USER:
            continue
        if path.startswith("/api/v1/platform/"):
            continue        # platform-admin routes answer 403 to ordinary users; covered by the platform test below
        headers = {}
        token = stranger.cookies.get("qc_csrf")
        if token:
            headers["X-CSRF-Token"] = token
        r = stranger.request(method, fill(path, clinic_id=b.env.cid), headers=headers,
                             json={} if method in {"POST", "PUT", "PATCH"} else None)
        if r.status_code != 404:
            leaks.append((method, path, r.status_code))
    assert leaks == [], f"clinic routes that did not answer 404 to a non-member: {leaks}"


@pytest.mark.parametrize("path", ["/api/v1/platform/clinics", "/api/v1/platform/audit-logs"])
def test_platform_routes_reject_ordinary_users(client, path):
    signup(client, "ordinary@example.com")
    assert client.get(path).status_code == 403
