"""Real-time gateway: mint a WebSocket ticket (REST) and the WebSocket endpoint itself.

Protocol (full description in docs/realtime.md)
  client -> POST /api/v1/clinics/{clinic_id}/realtime/ticket     (cookie session + CSRF)
  client -> GET  /api/v1/ws?ticket=...                           (upgrade to WebSocket)
  server -> {"type":"ready"}                                    connection accepted
  server -> {"type":"event","id","event","version","ts","data"}  at-least-once; dedupe on `id`
  server -> {"type":"resync"}                                   events may have been missed: refetch via REST
  client -> {"type":"ping"}   server -> {"type":"pong"}
Anything else from the client closes the connection. Clients never choose channels.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.api.deps import AuthContext, TenantContext, get_auth_context, require_clinic_role
from app.core.config import Settings, get_settings
from app.core.database import get_sessionmaker, set_rls_context
from app.core.ratelimit import get_client_ip, rate_limit
from app.core.security import utcnow
from app.models import Clinic, ClinicMembership, Doctor, User, UserSession
from app.permissions.roles import ClinicRole, ClinicStatus
from app.schemas.realtime import TicketOut
from app.websocket.broker import get_broker
from app.websocket.channels import channels_for
from app.websocket.hub import CLOSE_POLICY, Hub, HubLimitError
from app.websocket.tickets import TicketError, get_ticket_store, issue_ticket, verify_ticket

log = logging.getLogger("queuecare.ws")
router = APIRouter(tags=["realtime"])

ANY_MEMBER = require_clinic_role(*ClinicRole)
MAX_CLIENT_MESSAGE_CHARS = 256
PONG = json.dumps({"type": "pong"}, separators=(",", ":"))
READY = json.dumps({"type": "ready"}, separators=(",", ":"))
CLOSE_GOING_AWAY, CLOSE_UNSUPPORTED, CLOSE_TOO_BIG = 1001, 1003, 1009


@router.post("/clinics/{clinic_id}/realtime/ticket", response_model=TicketOut,
             dependencies=[Depends(rate_limit("ws_ticket", 30, 60))])
def create_ticket(request: Request, tenant: TenantContext = Depends(ANY_MEMBER),
                  auth: AuthContext = Depends(get_auth_context),
                  settings: Settings = Depends(get_settings)) -> TicketOut:
    """Short-lived single-use ticket for opening a WebSocket for this clinic. Any active member may ask."""
    ticket = issue_ticket(settings.jwt_secret, settings.jwt_algorithm, user_id=tenant.user.id,
                          clinic_id=tenant.clinic.id, session_id=auth.session_id,
                          ttl_seconds=settings.ws_ticket_ttl_seconds)
    return TicketOut(ticket=ticket, expires_in=settings.ws_ticket_ttl_seconds)


@dataclass(frozen=True)
class Access:
    role: ClinicRole
    doctor_id: uuid.UUID | None


def resolve_access(user_id: uuid.UUID, clinic_id: uuid.UUID, session_id: uuid.UUID) -> Access | None:
    """Re-derive what this user may receive from the database (blocking; run in a worker thread).
    Returns None when the login session, user, membership or clinic is no longer valid."""
    with get_sessionmaker()() as db:
        set_rls_context(db, user_id=user_id)
        session = db.get(UserSession, session_id)
        if (session is None or session.user_id != user_id or session.revoked_at is not None
                or session.expires_at <= utcnow()):
            return None
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        roles = {ClinicRole(r) for r in db.scalars(select(ClinicMembership.role).where(
            ClinicMembership.clinic_id == clinic_id, ClinicMembership.user_id == user_id,
            ClinicMembership.is_active.is_(True)))}
        if not roles:
            return None
        set_rls_context(db, user_id=user_id, clinic_id=clinic_id)
        clinic = db.get(Clinic, clinic_id)
        if clinic is None or clinic.status != ClinicStatus.ACTIVE:
            return None
        role = next(r for r in ClinicRole if r in roles)           # same precedence as REST
        doctor_id = None
        if role == ClinicRole.DOCTOR:
            doctor_id = db.scalar(select(Doctor.id).where(
                Doctor.clinic_id == clinic_id, Doctor.user_id == user_id, Doctor.is_active.is_(True)))
        return Access(role, doctor_id)


async def _reject(ws: WebSocket, code: int = CLOSE_POLICY) -> None:
    await ws.close(code=code)       # before accept(): the client sees a refused handshake (HTTP 403)


@router.websocket("/ws")
async def gateway(ws: WebSocket, settings: Settings = Depends(get_settings)) -> None:
    # 1. Cross-site WebSocket hijacking: a browser-supplied Origin must be one of ours.
    origin = ws.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.cors_origins:
        await _reject(ws)
        return

    # 2. Ticket: signature, expiry, audience, then single use.
    try:
        claims = verify_ticket(settings.jwt_secret, settings.jwt_algorithm, ws.query_params.get("ticket", ""))
    except TicketError:
        await _reject(ws)
        return
    store = get_ticket_store(settings.redis_url)
    if not await asyncio.to_thread(store.consume, claims.jti, settings.ws_ticket_ttl_seconds * 2):
        await _reject(ws)
        return

    # 3. Authorization comes from the database, not from the ticket.
    access = await asyncio.to_thread(resolve_access, claims.user_id, claims.clinic_id, claims.session_id)
    if access is None:
        await _reject(ws)
        return
    channels = channels_for(access.role, clinic_id=claims.clinic_id, user_id=claims.user_id,
                            doctor_id=access.doctor_id)

    hub: Hub = ws.app.state.hub
    hub.ensure_attached(get_broker(settings.redis_url))
    try:
        conn = hub.register(str(claims.user_id), get_client_ip(ws, settings), channels)  # type: ignore[arg-type]
    except HubLimitError:
        await _reject(ws, code=1013)
        return

    await ws.accept()
    conn.queue.put_nowait(READY)

    async def sender() -> None:
        try:
            while True:
                await ws.send_text(await conn.queue.get())
        except Exception:  # noqa: BLE001  (client went away)
            return

    async def receiver() -> None:
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=settings.ws_idle_timeout_seconds)
                except TimeoutError:
                    conn.close_code = CLOSE_GOING_AWAY
                    return
                if len(raw) > MAX_CLIENT_MESSAGE_CHARS:
                    conn.close_code = CLOSE_TOO_BIG
                    return
                try:
                    message = json.loads(raw)
                except ValueError:
                    conn.close_code = CLOSE_UNSUPPORTED
                    return
                if message != {"type": "ping"}:                    # the only message clients may send
                    conn.close_code = CLOSE_POLICY
                    return
                conn.queue.put_nowait(PONG)                        # same queue: ordered after earlier events
        except WebSocketDisconnect:
            return

    async def watchdog() -> None:
        """Periodically re-check the session and membership so revoked access ends the connection."""
        while True:
            await asyncio.sleep(settings.ws_revalidate_seconds)
            current = await asyncio.to_thread(resolve_access, claims.user_id, claims.clinic_id, claims.session_id)
            if current is None or channels_for(current.role, clinic_id=claims.clinic_id, user_id=claims.user_id,
                                               doctor_id=current.doctor_id) != conn.channels:
                conn.close_code = CLOSE_POLICY
                return

    tasks = [asyncio.create_task(c()) for c in (sender, receiver, watchdog)]
    tasks.append(asyncio.create_task(conn.closed.wait()))
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        hub.unregister(conn)             # synchronous and first: a cancellation can never skip it
        # This handler is ending either way. If the whole handler is being cancelled (server shutdown,
        # or a test client tearing the session down), the awaits below may be interrupted again; that is
        # fine, the connection is already unregistered and its tasks are cancelled.
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)
            await ws.close(code=conn.close_code if conn.close_code != 1000 else 1000)
