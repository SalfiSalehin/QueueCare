"""FastAPI dependencies: authentication, CSRF/Origin checks, RBAC, and tenant resolution.

Authorization is enforced HERE on the server for every request. A clinic_id from the client
is only ever a *claim*: access is granted solely from an active clinic_memberships row.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import Settings, get_settings
from app.core.cookies import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER
from app.core.database import get_db, set_rls_context
from app.models import Clinic, ClinicMembership, User, UserSession
from app.permissions.roles import ClinicRole, ClinicStatus, PlatformRole

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _unauthorized(message: str = "Not authenticated.") -> HTTPException:
    return HTTPException(status_code=401, detail=message)


# --------------------------------------------------------------- CSRF / Origin
def origin_check(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """For state-changing requests, a browser-supplied Origin must be one we trust.
    Requests without Origin (non-browser clients) pass this check; they carry no ambient cookies."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.cors_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed.")


def csrf_protect(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Double-submit CSRF check for cookie-authenticated, state-changing requests.
    Requests authenticated by an Authorization header are not subject to CSRF."""
    if request.method in SAFE_METHODS or request.headers.get("authorization"):
        return
    origin_check(request, settings)
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not security.tokens_equal(cookie, header) or security.parse_csrf_token(header, settings) is None:
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


# --------------------------------------------------------------- authentication
@dataclass
class AuthContext:
    user: User
    session_id: uuid.UUID
    via_cookie: bool


def _extract_token(request: Request) -> tuple[str | None, bool]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip(), False
    return request.cookies.get(ACCESS_COOKIE), True


def get_auth_context(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AuthContext:
    token, via_cookie = _extract_token(request)
    if not token:
        raise _unauthorized()
    try:
        claims = security.decode_access_token(token, settings)
    except jwt.PyJWTError:
        raise _unauthorized("Invalid or expired credentials.") from None

    # Identity lookups happen with only the user bound, so RLS sees who is asking.
    set_rls_context(db, user_id=claims.user_id)
    session = db.get(UserSession, claims.session_id)
    now = security.utcnow()
    if (session is None or session.user_id != claims.user_id or session.revoked_at is not None
            or session.expires_at <= now):
        raise _unauthorized("Session expired.")
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Session expired.")
    request.state.user_id = user.id
    return AuthContext(user=user, session_id=session.id, via_cookie=via_cookie)


def get_current_user(ctx: AuthContext = Depends(get_auth_context)) -> User:
    return ctx.user


def authed_write(request: Request, _csrf: None = Depends(csrf_protect), ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Authenticated + CSRF-checked context for state-changing endpoints."""
    return ctx


# ---------------------------------------------------------------- platform RBAC
def require_super_admin(
    request: Request, _csrf: None = Depends(csrf_protect), ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> User:
    if ctx.user.platform_role != PlatformRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Platform administrator access required.")
    # Explicit, audited platform-level access: only now is the RLS platform flag raised.
    set_rls_context(db, user_id=ctx.user.id, platform=True)
    return ctx.user


# ------------------------------------------------------------------ tenant RBAC
@dataclass
class TenantContext:
    user: User
    clinic: Clinic
    role: ClinicRole


def require_clinic_role(
    *roles: ClinicRole, allow_inactive_clinic: bool = False
) -> Callable[..., TenantContext]:
    """Dependency factory. Resolves {clinic_id} from the path, verifies the caller has an active
    membership with one of `roles`, then binds the tenant to the DB session (RLS)."""
    allowed = set(roles)

    def dependency(
        clinic_id: uuid.UUID,
        request: Request,
        _csrf: None = Depends(csrf_protect),
        ctx: AuthContext = Depends(get_auth_context),
        db: Session = Depends(get_db),
    ) -> TenantContext:
        membership_roles = {
            ClinicRole(r)
            for r in db.scalars(
                select(ClinicMembership.role).where(
                    ClinicMembership.clinic_id == clinic_id,
                    ClinicMembership.user_id == ctx.user.id,
                    ClinicMembership.is_active.is_(True),
                )
            )
        }
        # 404 (not 403) for non-members so clinic existence is not revealed across tenants.
        if not membership_roles:
            raise HTTPException(status_code=404, detail="Clinic not found.")
        matched = membership_roles & allowed
        if not matched:
            raise HTTPException(status_code=403, detail="You do not have permission to do this.")

        clinic = db.get(Clinic, clinic_id)
        if clinic is None:
            raise HTTPException(status_code=404, detail="Clinic not found.")
        if clinic.status != ClinicStatus.ACTIVE and not allow_inactive_clinic:
            raise HTTPException(status_code=403, detail="This clinic is not active.")

        role = next(r for r in ClinicRole if r in matched)  # deterministic: highest-privilege first
        set_rls_context(db, user_id=ctx.user.id, clinic_id=clinic_id)
        request.state.clinic_id = clinic_id
        return TenantContext(user=ctx.user, clinic=clinic, role=role)

    return dependency
