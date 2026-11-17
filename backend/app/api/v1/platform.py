"""Platform (super administrator) endpoints. Every mutation is audited."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.ratelimit import get_client_ip
from app.models import AuditLog, Clinic, User
from app.permissions.roles import ClinicStatus
from app.schemas.clinic import ClinicSummary
from app.schemas.common import StrictModel
from app.services.audit_service import record_audit

router = APIRouter(prefix="/platform", tags=["platform"])


class StatusChange(StrictModel):
    status: ClinicStatus


class AuditOut(BaseModel):
    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    clinic_id: uuid.UUID | None
    created_at: datetime


@router.get("/clinics", response_model=list[ClinicSummary])
def all_clinics(status: ClinicStatus | None = None, db: Session = Depends(get_db),
                _admin: User = Depends(require_super_admin)) -> list[ClinicSummary]:
    stmt = select(Clinic).order_by(Clinic.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Clinic.status == status)
    return [ClinicSummary(id=c.id, name=c.name, slug=c.slug, status=c.status, timezone=c.timezone,
                          created_at=c.created_at) for c in db.scalars(stmt)]


@router.post("/clinics/{clinic_id}/status", response_model=ClinicSummary)
def set_clinic_status(clinic_id: uuid.UUID, body: StatusChange, request: Request, db: Session = Depends(get_db),
                      admin: User = Depends(require_super_admin),
                      settings: Settings = Depends(get_settings)) -> ClinicSummary:
    clinic = db.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(status_code=404, detail="Clinic not found.")
    previous = clinic.status
    clinic.status = body.status.value
    record_audit(db, action="platform.clinic_status_changed", actor_user_id=admin.id, clinic_id=clinic.id,
                 entity_type="clinic", entity_id=clinic.id, ip=get_client_ip(request, settings),
                 metadata={"from": previous, "to": body.status.value})
    db.commit()
    return ClinicSummary(id=clinic.id, name=clinic.name, slug=clinic.slug, status=clinic.status,
                         timezone=clinic.timezone, created_at=clinic.created_at)


@router.get("/audit-logs", response_model=list[AuditOut])
def audit_logs(limit: int = 50, db: Session = Depends(get_db),
               _admin: User = Depends(require_super_admin)) -> list[AuditOut]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 200))))
    return [AuditOut(id=r.id, action=r.action, actor_user_id=r.actor_user_id, clinic_id=r.clinic_id,
                     created_at=r.created_at) for r in rows]
