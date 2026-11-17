"""Notification delivery worker (EMAIL and SMS; IN_APP rows are already "delivered" when created).

Guarantees
- AT LEAST ONCE, never silently lost: a row stays PENDING until a provider accepted it or retries are
  exhausted (then FAILED, with the reason). A crash between "provider accepted" and "marked SENT" can make
  the provider see the same idempotency key twice; providers that support idempotent sends drop the
  duplicate. This is the same trade-off as the outbox relay.
- No double pickup by concurrent workers: a batch is CLAIMED first (FOR UPDATE SKIP LOCKED), each claimed
  row gets a lease (`next_attempt_at` pushed forward) and its attempt counter is incremented, and the claim
  is committed. Delivery then happens per row without holding locks. A worker that dies mid-batch leaves
  rows whose lease expires, after which they are claimed again; the attempt counter already includes the
  lost try, so a row that keeps crashing workers ends up FAILED instead of looping forever.
- Retries use exponential back-off (base * 2^(attempt-1), capped at 1 hour). A permanent provider error
  (e.g. invalid address) fails the row at once.
- A reminder is dropped (FAILED, "skipped") if its appointment is no longer CONFIRMED when it is about to
  be sent.

Like the outbox relay it reads across clinics, so it binds the explicit platform RLS context. It only
touches notification rows, plus read-only lookups of the recipient and the appointment.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import get_sessionmaker, set_rls_context
from app.models import Appointment, Clinic, Doctor, Notification, Patient, User
from app.services.notification_providers import (
    NotificationProvider, OutboundMessage, ProviderError, get_providers,
)
from app.services.notification_logic import backoff_seconds
from app.services.notification_service import enqueue
from app.services.notification_templates import render

log = logging.getLogger("queuecare.notifications")


@dataclass
class DispatchStats:
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Claim:
    id: Any
    user_id: Any
    channel: str
    type: str
    payload: dict[str, Any]
    key: str
    attempts: int


def claim_batch(factory: sessionmaker[Session], now: datetime, batch_size: int, max_attempts: int,
                lease_seconds: int) -> tuple[list[_Claim], int]:
    """Lock due rows, give each a lease and count the attempt, commit. Returns (claims, exhausted_count)."""
    claims: list[_Claim] = []
    exhausted = 0
    with factory() as db:
        set_rls_context(db, platform=True)
        rows = db.scalars(
            select(Notification)
            .where(Notification.status == "PENDING", Notification.channel.in_(("EMAIL", "SMS")),
                   or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at <= now))
            .order_by(Notification.created_at).limit(batch_size).with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            if row.attempts >= max_attempts:           # a worker kept dying on this row: stop retrying
                row.status, row.next_attempt_at = "FAILED", None
                row.last_error = "gave up: attempts exhausted"
                exhausted += 1
                continue
            row.attempts += 1
            row.next_attempt_at = now + timedelta(seconds=lease_seconds)
            claims.append(_Claim(row.id, row.user_id, row.channel, row.type, dict(row.payload),
                                 row.idempotency_key, row.attempts))
        db.commit()
    return claims, exhausted


def _deliver(factory: sessionmaker[Session], providers: dict[str, NotificationProvider], claim: _Claim,
             now: datetime, max_attempts: int, backoff_base: int) -> str:
    """Send one claimed row and record the outcome. Returns "sent" | "retry" | "failed"."""
    error: str | None = None
    permanent = False
    with factory() as db:
        set_rls_context(db, platform=True)
        user = db.get(User, claim.user_id)
        recipient = None if user is None or not user.is_active else (
            user.email if claim.channel == "EMAIL" else user.phone)
        if not recipient:
            error, permanent = "recipient unavailable (inactive account or no address/number)", True
        elif claim.type == "appointment.reminder" and not _still_confirmed(db, claim.payload):
            error, permanent = "skipped: appointment is no longer confirmed", True
        else:
            try:
                title, body = render(claim.type, claim.payload)
                providers[claim.channel].send(OutboundMessage(
                    channel=claim.channel, to=recipient, subject=title, body=body, kind=claim.type,
                    idempotency_key=claim.key))
            except ProviderError as exc:
                error, permanent = str(exc)[:200], exc.permanent
            except Exception as exc:  # noqa: BLE001  (never store arbitrary exception text: it may hold addresses)
                error = type(exc).__name__
                log.warning("notification delivery failed (%s) kind=%s attempt=%d", error, claim.type, claim.attempts)

        row = db.scalar(select(Notification).where(Notification.id == claim.id).with_for_update())
        if row is None or row.status != "PENDING":
            return "sent" if error is None else "failed"
        if error is None:
            row.status, row.next_attempt_at, row.last_error = "SENT", None, None
            outcome = "sent"
        elif permanent or claim.attempts >= max_attempts:
            row.status, row.next_attempt_at, row.last_error = "FAILED", None, error
            outcome = "failed"
        else:
            row.next_attempt_at = now + timedelta(seconds=backoff_seconds(claim.attempts, backoff_base))
            row.last_error = error
            outcome = "retry"
        db.commit()
        return outcome


def _still_confirmed(db: Session, payload: dict[str, Any]) -> bool:
    appointment_id = payload.get("appointment_id")
    if not appointment_id:
        return True
    status = db.scalar(select(Appointment.status).where(Appointment.id == appointment_id))
    return status == "CONFIRMED"


def dispatch_batch(factory: sessionmaker[Session], providers: dict[str, NotificationProvider] | None = None, *,
                   now: datetime | None = None, batch_size: int = 50, max_attempts: int = 5,
                   backoff_base: int = 30, lease_seconds: int = 120) -> DispatchStats:
    providers = providers or get_providers()
    now = now or datetime.now(UTC)
    claims, exhausted = claim_batch(factory, now, batch_size, max_attempts, lease_seconds)
    stats = DispatchStats(claimed=len(claims), failed=exhausted)
    for claim in claims:
        outcome = _deliver(factory, providers, claim, now, max_attempts, backoff_base)
        if outcome == "sent":
            stats.sent += 1
        elif outcome == "retry":
            stats.retried += 1
        else:
            stats.failed += 1
    return stats


def schedule_reminders(factory: sessionmaker[Session], now: datetime, lead_hours: int, limit: int = 500) -> int:
    """Create reminder notifications for confirmed appointments starting within `lead_hours`.

    Idempotent: the key includes the appointment id and its start time, so running this every few
    minutes never duplicates a reminder. Returns how many notification rows were newly created."""
    created = 0
    with factory() as db:
        set_rls_context(db, platform=True)
        rows = db.execute(
            select(Appointment, Patient.user_id, Clinic.name, Clinic.timezone, Doctor.display_name)
            .join(Patient, (Patient.id == Appointment.patient_id) & (Patient.clinic_id == Appointment.clinic_id))
            .join(Clinic, Clinic.id == Appointment.clinic_id)
            .join(Doctor, (Doctor.id == Appointment.doctor_id) & (Doctor.clinic_id == Appointment.clinic_id))
            .where(Appointment.status == "CONFIRMED", Appointment.starts_at > now,
                   Appointment.starts_at <= now + timedelta(hours=lead_hours), Patient.user_id.is_not(None))
            .order_by(Appointment.starts_at).limit(limit)
        ).all()
        for appt, user_id, clinic_name, tz, doctor_name in rows:
            created += enqueue(
                db, clinic_id=appt.clinic_id, user_id=user_id, kind="appointment.reminder",
                entity_key=f"{appt.id}:{int(appt.starts_at.timestamp())}",
                payload={"clinic_name": clinic_name, "doctor_name": doctor_name,
                         "starts_at": appt.starts_at.isoformat(), "tz": tz, "appointment_id": str(appt.id)})
        db.commit()
    return created


def purge_old(factory: sessionmaker[Session], retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    with factory() as db:
        set_rls_context(db, platform=True)
        result = db.execute(delete(Notification).where(
            Notification.created_at < cutoff, Notification.status.in_(("SENT", "READ", "FAILED"))))
        db.commit()
        return int(result.rowcount or 0)


async def notification_loop(settings: Settings) -> None:
    """Background task started with the API. Cancelled on shutdown."""
    factory = get_sessionmaker()
    loop = asyncio.get_running_loop()
    last_reminders = last_purge = float("-inf")
    while True:
        delay = settings.notification_poll_interval_seconds
        try:
            if loop.time() - last_reminders > 300:
                last_reminders = loop.time()
                made = await asyncio.to_thread(schedule_reminders, factory, datetime.now(UTC),
                                               settings.notification_reminder_hours)
                if made:
                    log.info("notifications: created %d reminder(s)", made)
            stats = await asyncio.to_thread(
                dispatch_batch, factory, None, batch_size=settings.notification_batch_size,
                max_attempts=settings.notification_max_attempts,
                backoff_base=settings.notification_backoff_base_seconds,
                lease_seconds=settings.notification_lease_seconds)
            if stats.claimed >= settings.notification_batch_size:
                delay = 0
            if loop.time() - last_purge > 3600:
                last_purge = loop.time()
                await asyncio.to_thread(purge_old, factory, settings.notification_retention_days)
        except Exception:  # noqa: BLE001
            log.exception("notification worker: unexpected error")
            delay = max(delay, 5.0)
        await asyncio.sleep(delay)
