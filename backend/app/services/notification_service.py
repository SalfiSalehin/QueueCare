"""Creating and reading notifications.

Creation (`enqueue`) runs in the CALLER'S transaction: the notification exists if and only if the change
that caused it was committed (same idea as the real-time outbox). It is idempotent: the unique
`idempotency_key` (type + entity + version + recipient + channel) turns a repeated enqueue into a no-op.

Channels
- IN_APP: always. The row itself is the delivery (status SENT, READ once the user opens it).
- EMAIL: only to a VERIFIED address (never to an address nobody proved they own).
- SMS: only for time-critical types (reminder, "your turn") and only if the user has a phone number. There
  is no phone verification or consent record yet, so SMS stays off for everything else.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.errors import ServiceError
from app.models import Appointment, Doctor, Notification, Patient, QueueToken, User
from app.schemas.common import Page
from app.schemas.notifications import NotificationOut
from app.services.notification_logic import channels_for
from app.services.notification_templates import render

log = logging.getLogger("queuecare.notifications")


def enqueue(db: Session, *, clinic_id: uuid.UUID, user_id: uuid.UUID, kind: str, entity_key: str,
            payload: dict[str, Any]) -> int:
    """Insert one row per channel; returns how many were new (0 when everything already existed)."""
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return 0
    rows = [{
        "id": uuid.uuid4(), "clinic_id": clinic_id, "user_id": user_id, "channel": channel, "type": kind,
        "status": "SENT" if channel == "IN_APP" else "PENDING", "attempts": 0, "payload": payload,
        "idempotency_key": f"{kind}:{entity_key}:{user_id}:{channel}",
    } for channel in channels_for(user, kind)]
    inserted = db.execute(pg_insert(Notification).values(rows).on_conflict_do_nothing(
        index_elements=["idempotency_key"]).returning(Notification.id)).all()
    return len(inserted)             # RETURNING, not rowcount: rowcount is unreliable for multi-row inserts


def _safely(db: Session, what: str, fn: Any) -> None:
    """Notifications must never break the action that triggered them: run in a savepoint, log failures."""
    db.flush()      # the caller's own pending changes: errors here are NOT notification problems, let them out
    try:
        with db.begin_nested():
            fn()
    except Exception:  # noqa: BLE001
        log.exception("could not enqueue %s notification", what)


def notify_appointment(db: Session, tenant: TenantContext, appt: Appointment, kind: str,
                       patient_user_id: uuid.UUID | None | str = "lookup") -> None:
    """Tell the patient (if they have an account) about an appointment change."""
    def run() -> None:
        user_id = patient_user_id
        if user_id == "lookup":
            user_id = db.scalar(select(Patient.user_id).where(Patient.id == appt.patient_id,
                                                              Patient.clinic_id == tenant.clinic.id))
        if user_id is None:
            return
        doctor = db.scalar(select(Doctor.display_name).where(Doctor.id == appt.doctor_id,
                                                              Doctor.clinic_id == tenant.clinic.id))
        enqueue(db, clinic_id=tenant.clinic.id, user_id=user_id, kind=kind,  # type: ignore[arg-type]
                entity_key=str(appt.id),
                payload={"clinic_name": tenant.clinic.name, "doctor_name": doctor or "your doctor",
                         "starts_at": appt.starts_at.isoformat(), "tz": tenant.clinic.timezone,
                         "appointment_id": str(appt.id)})
    _safely(db, kind, run)


def notify_token_called(db: Session, tenant: TenantContext, token: QueueToken) -> None:
    def run() -> None:
        user_id = db.scalar(select(Patient.user_id).where(Patient.id == token.patient_id,
                                                          Patient.clinic_id == tenant.clinic.id))
        if user_id is None:
            return
        doctor = db.scalar(select(Doctor.display_name).where(Doctor.id == token.doctor_id,
                                                              Doctor.clinic_id == tenant.clinic.id))
        enqueue(db, clinic_id=tenant.clinic.id, user_id=user_id, kind="queue.called",
                entity_key=f"{token.id}:{token.version}",
                payload={"clinic_name": tenant.clinic.name, "doctor_name": doctor or "your doctor",
                         "token_label": token.token_label, "token_id": str(token.id)})
    _safely(db, "queue.called", run)


class NotificationService:
    """A member's own in-app notifications. Always scoped to the signed-in user AND the clinic in context."""

    def __init__(self, db: Session, tenant: TenantContext) -> None:
        self.db = db
        self.clinic_id = tenant.clinic.id
        self.user_id = tenant.user.id

    def _mine(self) -> list[Any]:
        return [Notification.clinic_id == self.clinic_id, Notification.user_id == self.user_id,
                Notification.channel == "IN_APP"]

    @staticmethod
    def _out(row: Notification) -> NotificationOut:
        title, body = render(row.type, row.payload)
        return NotificationOut(id=row.id, type=row.type, title=title, body=body, read=row.status == "READ",
                               created_at=row.created_at)

    def list(self, unread_only: bool, limit: int, offset: int) -> Page[NotificationOut]:
        where = self._mine() + ([Notification.status != "READ"] if unread_only else [])
        total = self.db.scalar(select(func.count()).select_from(Notification).where(*where)) or 0
        rows = self.db.scalars(select(Notification).where(*where)
                               .order_by(Notification.created_at.desc(), Notification.id)
                               .limit(limit).offset(offset)).all()
        return Page(items=[self._out(r) for r in rows], total=total, limit=limit, offset=offset)

    def unread_count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(Notification)
                              .where(*self._mine(), Notification.status != "READ")) or 0

    def mark_read(self, notification_id: uuid.UUID) -> NotificationOut:
        row = self.db.scalar(select(Notification).where(Notification.id == notification_id, *self._mine()))
        if row is None:
            raise ServiceError(404, "Notification not found.")      # someone else's looks nonexistent
        if row.status != "READ":
            row.status = "READ"
            self.db.commit()
        return self._out(row)

    def mark_all_read(self) -> int:
        result = self.db.execute(update(Notification).where(*self._mine(), Notification.status != "READ")
                                 .values(status="READ"))
        self.db.commit()
        return int(result.rowcount or 0)
