"""Clinic endpoints (Phase 2 scope: registration, directory, membership). Full CRUD arrives in Phase 3."""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, TenantContext, authed_write, get_auth_context, require_clinic_role
from app.core.config import Settings, get_settings
from app.core.database import get_db, set_rls_context
from app.core.ratelimit import get_client_ip
from app.models import Clinic, ClinicMembership, Patient, User
from app.permissions.roles import ClinicRole, ClinicStatus
from app.schemas.clinic import ClinicDetail, ClinicSummary, MemberOut, clinic_detail
from app.schemas.common import Page, StrictModel
from app.services.audit_service import record_audit

router = APIRouter(prefix="/clinics", tags=["clinics"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


class ClinicCreate(StrictModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=3, max_length=63)
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.lower()
        if not _SLUG_RE.match(v):
            raise ValueError("Slug may contain lowercase letters, digits and hyphens only")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        return v


class MemberAdd(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role: ClinicRole


def _summary(c: Clinic) -> ClinicSummary:
    return ClinicSummary(id=c.id, name=c.name, slug=c.slug, status=c.status, timezone=c.timezone,
                         created_at=c.created_at)


@router.get("", response_model=Page[ClinicSummary])
def list_clinics(limit: int = 20, offset: int = 0, db: Session = Depends(get_db),
                 _ctx: AuthContext = Depends(get_auth_context)) -> Page[ClinicSummary]:
    """Public directory: only ACTIVE clinics, minimal fields."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    base = select(Clinic).where(Clinic.status == ClinicStatus.ACTIVE)
    from sqlalchemy import func
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Clinic.name).limit(limit).offset(offset)).all()
    return Page(items=[_summary(c) for c in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ClinicSummary, status_code=201)
def register_clinic(body: ClinicCreate, request: Request, ctx: AuthContext = Depends(authed_write),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> ClinicSummary:
    """Register a clinic. It starts PENDING until a platform administrator approves it;
    the creator becomes its CLINIC_ADMIN."""
    clinic = Clinic(name=body.name, slug=body.slug, timezone=body.timezone, status=ClinicStatus.PENDING)
    db.add(clinic)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That clinic address is already taken.") from None
    db.add(ClinicMembership(clinic_id=clinic.id, user_id=ctx.user.id, role=ClinicRole.CLINIC_ADMIN))
    record_audit(db, action="clinic.registered", actor_user_id=ctx.user.id, clinic_id=clinic.id,
                 entity_type="clinic", entity_id=clinic.id, ip=get_client_ip(request, settings))
    db.commit()
    return _summary(clinic)


@router.get("/{clinic_id}", response_model=ClinicDetail)
def get_clinic(tenant: TenantContext = Depends(require_clinic_role(*ClinicRole, allow_inactive_clinic=True))) -> ClinicDetail:
    return clinic_detail(tenant.clinic)


@router.get("/{clinic_id}/members", response_model=list[MemberOut])
def list_members(tenant: TenantContext = Depends(require_clinic_role(ClinicRole.CLINIC_ADMIN)),
                 db: Session = Depends(get_db)) -> list[MemberOut]:
    rows = db.execute(
        select(ClinicMembership, User).join(User, User.id == ClinicMembership.user_id)
        .where(ClinicMembership.clinic_id == tenant.clinic.id).order_by(User.full_name)
    ).all()
    return [MemberOut(membership_id=m.id, user_id=u.id, full_name=u.full_name, email=u.email, role=m.role,
                      is_active=m.is_active) for m, u in rows]


@router.post("/{clinic_id}/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberAdd, request: Request,
               tenant: TenantContext = Depends(require_clinic_role(ClinicRole.CLINIC_ADMIN)),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> MemberOut:
    """Attach an EXISTING user account to this clinic with a role (staff onboarding)."""
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="No active user with that email.")
    existing = db.scalar(select(ClinicMembership).where(
        ClinicMembership.clinic_id == tenant.clinic.id, ClinicMembership.user_id == user.id,
        ClinicMembership.role == body.role))
    if existing:
        raise HTTPException(status_code=409, detail="User already has that role in this clinic.")
    membership = ClinicMembership(id=uuid.uuid4(), clinic_id=tenant.clinic.id, user_id=user.id, role=body.role)
    db.add(membership)
    record_audit(db, action="clinic.member_added", actor_user_id=tenant.user.id, clinic_id=tenant.clinic.id,
                 entity_type="user", entity_id=user.id, ip=get_client_ip(request, settings),
                 metadata={"role": body.role.value})
    db.commit()
    return MemberOut(membership_id=membership.id, user_id=user.id, full_name=user.full_name, email=user.email,
                     role=body.role.value, is_active=True)


@router.post("/{clinic_id}/join", status_code=204)
def join_as_patient(clinic_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(authed_write),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> None:
    """A signed-in user becomes a PATIENT of an ACTIVE clinic. Self-service grants only this role.

    Joining also creates the person's patient profile in that clinic, so reception can find them for a walk-in and
    their own queue screen shows their tokens. Safe to call repeatedly: it never creates a second membership or profile.
    """
    clinic = db.get(Clinic, clinic_id)
    if clinic is None or clinic.status != ClinicStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Clinic not found.")
    exists = db.scalar(select(ClinicMembership.id).where(
        ClinicMembership.clinic_id == clinic_id, ClinicMembership.user_id == ctx.user.id,
        ClinicMembership.role == ClinicRole.PATIENT))
    if not exists:
        db.add(ClinicMembership(clinic_id=clinic_id, user_id=ctx.user.id, role=ClinicRole.PATIENT))
        record_audit(db, action="clinic.patient_joined", actor_user_id=ctx.user.id, clinic_id=clinic_id,
                     ip=get_client_ip(request, settings))
        db.flush()
    # The patients table is row-level-secured per clinic. Only now, after the clinic is confirmed ACTIVE, is the
    # clinic bound to this session, and only for this user's own profile.
    set_rls_context(db, user_id=ctx.user.id, clinic_id=clinic_id)
    stmt = select(Patient.id).where(Patient.clinic_id == clinic_id, Patient.user_id == ctx.user.id,
                                    Patient.deleted_at.is_(None))
    if db.scalar(stmt) is None:
        try:
            with db.begin_nested():  # savepoint: losing a race to a concurrent join must not poison the transaction
                db.add(Patient(id=uuid.uuid4(), clinic_id=clinic_id, user_id=ctx.user.id,
                               full_name=ctx.user.full_name, phone=ctx.user.phone))
                db.flush()
        except IntegrityError:
            pass  # the unique index (clinic_id, user_id) says the other request created it first
    db.commit()
