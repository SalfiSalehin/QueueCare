"""Auth cookie helpers.

- qc_access : short-lived JWT, HttpOnly
- qc_refresh: opaque rotating token, HttpOnly, scoped to /api/v1/auth only
- qc_csrf   : signed double-submit token, readable by JS on same-site deployments
"""
from __future__ import annotations

from fastapi import Response

from app.core.config import Settings

ACCESS_COOKIE = "qc_access"
REFRESH_COOKIE = "qc_refresh"
CSRF_COOKIE = "qc_csrf"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _common(settings: Settings) -> dict[str, object]:
    return {"secure": settings.cookie_secure, "samesite": settings.cookie_samesite, "domain": settings.cookie_domain}


def set_auth_cookies(
    response: Response, settings: Settings, *, access: str, refresh: str, csrf: str
) -> None:
    common = _common(settings)
    refresh_age = settings.refresh_token_ttl_days * 86400
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.access_token_ttl_minutes * 60,
                        path="/", httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=refresh_age,
                        path=REFRESH_COOKIE_PATH, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(CSRF_COOKIE, csrf, max_age=refresh_age,
                        path="/", httponly=False, **common)  # type: ignore[arg-type]


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    common = _common(settings)
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, **common)  # type: ignore[arg-type]
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, **common)  # type: ignore[arg-type]
    response.delete_cookie(CSRF_COOKIE, path="/", **common)  # type: ignore[arg-type]
