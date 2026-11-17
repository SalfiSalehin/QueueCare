"""Authentication endpoints. Business logic lives in AuthService."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, authed_write, csrf_protect, get_auth_context, origin_check
from app.core.errors import error_body
from app.core import security
from app.core.config import Settings, get_settings
from app.core.cookies import CSRF_COOKIE, REFRESH_COOKIE, clear_auth_cookies, set_auth_cookies
from app.core.database import get_db
from app.core.ratelimit import get_client_ip, rate_limit
from app.models import ClinicMembership, UserSession
from app.schemas.auth import (
    AuthResponse, ForgotPasswordRequest, LoginRequest, MeResponse, MembershipOut, RegisterRequest,
    ResetPasswordRequest, SessionOut, UserOut, VerifyEmailRequest,
)
from app.services.auth_service import AuthError, AuthService, IssuedSession
from app.services.email import EmailProvider, get_email_provider

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
    email: EmailProvider = Depends(get_email_provider),
) -> AuthService:
    return AuthService(db, settings, email)


def _fail(exc: AuthError) -> Exception:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _respond(response: Response, issued: IssuedSession, settings: Settings) -> AuthResponse:
    set_auth_cookies(response, settings, access=issued.access_token, refresh=issued.refresh_token,
                     csrf=issued.csrf_token)
    return AuthResponse(user=UserOut.model_validate(issued.user), csrf_token=issued.csrf_token)


@router.post("/register", status_code=201, response_model=UserOut,
             dependencies=[Depends(origin_check), Depends(rate_limit("register", 10, 3600))])
def register(body: RegisterRequest, request: Request, svc: AuthService = Depends(get_auth_service),
             settings: Settings = Depends(get_settings)) -> UserOut:
    try:
        body.check_password_against_email()
        user = svc.register(email=str(body.email), password=body.password, full_name=body.full_name,
                            phone=body.phone, ip=get_client_ip(request, settings))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except AuthError as exc:
        raise _fail(exc) from None
    return UserOut.model_validate(user)


@router.post("/login", response_model=AuthResponse,
             dependencies=[Depends(origin_check), Depends(rate_limit("login", 20, 300))])
def login(body: LoginRequest, request: Request, response: Response, svc: AuthService = Depends(get_auth_service),
          settings: Settings = Depends(get_settings)) -> AuthResponse:
    try:
        issued = svc.login(email=str(body.email), password=body.password, ip=get_client_ip(request, settings),
                           user_agent=request.headers.get("user-agent"))
    except AuthError as exc:
        raise _fail(exc) from None
    return _respond(response, issued, settings)


@router.post("/refresh", response_model=AuthResponse,
             dependencies=[Depends(csrf_protect), Depends(rate_limit("refresh", 60, 300))])
def refresh(request: Request, response: Response, svc: AuthService = Depends(get_auth_service),
            settings: Settings = Depends(get_settings)) -> AuthResponse | JSONResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        issued = svc.refresh(refresh_token=token, ip=get_client_ip(request, settings),
                             user_agent=request.headers.get("user-agent"))
    except AuthError as exc:
        # Return (not raise) so the cookie-clearing headers actually reach the browser.
        failed = JSONResponse(error_body(exc.status, exc.message, request), status_code=exc.status)
        clear_auth_cookies(failed, settings)
        return failed
    return _respond(response, issued, settings)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, ctx: AuthContext = Depends(authed_write),
           svc: AuthService = Depends(get_auth_service), settings: Settings = Depends(get_settings)) -> Response:
    svc.logout(ctx.session_id, ip=get_client_ip(request, settings))
    out = Response(status_code=204)
    clear_auth_cookies(out, settings)
    return out


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, ctx: AuthContext = Depends(authed_write),
               svc: AuthService = Depends(get_auth_service), settings: Settings = Depends(get_settings)) -> Response:
    svc.logout_all(ctx.user.id, ip=get_client_ip(request, settings))
    out = Response(status_code=204)
    clear_auth_cookies(out, settings)
    return out


@router.get("/me", response_model=MeResponse)
def me(request: Request, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db),
       settings: Settings = Depends(get_settings)) -> MeResponse:
    rows = db.scalars(select(ClinicMembership).where(
        ClinicMembership.user_id == ctx.user.id, ClinicMembership.is_active.is_(True)))
    return MeResponse(
        user=UserOut.model_validate(ctx.user),
        memberships=[MembershipOut(clinic_id=m.clinic_id, role=m.role) for m in rows],
        csrf_token=request.cookies.get(CSRF_COOKIE) or security.create_csrf_token(ctx.session_id, settings),
    )


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> list[SessionOut]:
    now = security.utcnow()
    rows = db.scalars(select(UserSession).where(
        UserSession.user_id == ctx.user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > now,
    ).order_by(UserSession.last_seen_at.desc()))
    return [SessionOut(id=s.id, created_at=s.created_at, last_seen_at=s.last_seen_at, ip=str(s.ip) if s.ip else None,
                       user_agent=s.user_agent, current=s.id == ctx.session_id) for s in rows]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(authed_write),
                   svc: AuthService = Depends(get_auth_service), settings: Settings = Depends(get_settings)) -> Response:
    if not svc.revoke_one(ctx.user.id, session_id, ip=get_client_ip(request, settings)):
        raise HTTPException(status_code=404, detail="Session not found.")
    return Response(status_code=204)


@router.post("/forgot-password", status_code=202,
             dependencies=[Depends(origin_check), Depends(rate_limit("forgot", 5, 3600))])
def forgot_password(body: ForgotPasswordRequest, request: Request, svc: AuthService = Depends(get_auth_service),
                    settings: Settings = Depends(get_settings)) -> dict[str, str]:
    svc.forgot_password(str(body.email), ip=get_client_ip(request, settings))
    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password", status_code=204,
             dependencies=[Depends(origin_check), Depends(rate_limit("reset", 10, 3600))])
def reset_password(body: ResetPasswordRequest, request: Request, svc: AuthService = Depends(get_auth_service),
                   settings: Settings = Depends(get_settings)) -> Response:
    try:
        svc.reset_password(token=body.token, new_password=body.new_password, ip=get_client_ip(request, settings))
    except AuthError as exc:
        raise _fail(exc) from None
    return Response(status_code=204)


@router.post("/verify-email", status_code=204,
             dependencies=[Depends(origin_check), Depends(rate_limit("verify", 20, 3600))])
def verify_email(body: VerifyEmailRequest, request: Request, svc: AuthService = Depends(get_auth_service),
                 settings: Settings = Depends(get_settings)) -> Response:
    try:
        svc.verify_email(token=body.token, ip=get_client_ip(request, settings))
    except AuthError as exc:
        raise _fail(exc) from None
    return Response(status_code=204)
