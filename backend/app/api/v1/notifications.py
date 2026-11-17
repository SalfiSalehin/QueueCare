"""A member's own in-app notifications. Delivery to email/SMS is done by the background worker."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, require_clinic_role
from app.core.database import get_db
from app.permissions.roles import ClinicRole
from app.schemas.common import Page
from app.schemas.notifications import NotificationOut, UnreadCount
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/clinics/{clinic_id}/notifications", tags=["notifications"])
ANY_MEMBER = require_clinic_role(*ClinicRole)


@router.get("", response_model=Page[NotificationOut])
def list_notifications(unread: bool = False, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                       tenant: TenantContext = Depends(ANY_MEMBER), db: Session = Depends(get_db)):
    return NotificationService(db, tenant).list(unread, limit, offset)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(tenant: TenantContext = Depends(ANY_MEMBER), db: Session = Depends(get_db)) -> UnreadCount:
    return UnreadCount(count=NotificationService(db, tenant).unread_count())


@router.post("/read-all", response_model=UnreadCount)
def read_all(tenant: TenantContext = Depends(ANY_MEMBER), db: Session = Depends(get_db)) -> UnreadCount:
    """Marks everything read; the returned count is how many were changed."""
    return UnreadCount(count=NotificationService(db, tenant).mark_all_read())


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_one(notification_id: uuid.UUID, tenant: TenantContext = Depends(ANY_MEMBER),
             db: Session = Depends(get_db)) -> NotificationOut:
    return NotificationService(db, tenant).mark_read(notification_id)
