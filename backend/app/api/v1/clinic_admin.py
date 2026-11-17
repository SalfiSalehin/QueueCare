"""Clinic management endpoints (all under /clinics/{clinic_id}).

Access matrix
  read departments / doctors / schedules : any active member of the clinic (patients see active doctors only)
  doctor status                          : admin, receptionist, or the doctor themself
  time off (read/write)                  : staff (admin/receptionist/doctor read; admin writes)
  everything else that writes            : CLINIC_ADMIN
Handlers stay thin: rules live in ClinicAdminService.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, require_clinic_role
from app.core.config import get_settings
from app.core.database import get_db
from app.core.ratelimit import get_client_ip
from app.models import ClinicMembership, User
from app.permissions.roles import ClinicRole
from app.schemas.clinic import ClinicDetail, ClinicUpdate, MemberOut, MemberUpdate, clinic_detail
from app.schemas.clinic_ops import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    DoctorCreate,
    DoctorOut,
    DoctorStatusUpdate,
    DoctorUpdate,
    ScheduleCreate,
    ScheduleOut,
    TimeOffCreate,
    TimeOffOut,
)
from app.schemas.common import Page
from app.services.clinic_admin_service import ClinicAdminService

router = APIRouter(prefix="/clinics/{clinic_id}", tags=["clinic management"])

ANY_MEMBER = require_clinic_role(*ClinicRole)
STAFF = require_clinic_role(ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST, ClinicRole.DOCTOR)
STATUS_EDITORS = STAFF
ADMIN = require_clinic_role(ClinicRole.CLINIC_ADMIN)


def _svc(db: Session, tenant: TenantContext, request: Request) -> ClinicAdminService:
    return ClinicAdminService(db, tenant, ip=get_client_ip(request, get_settings()))


def _dept(d) -> DepartmentOut:  # noqa: ANN001
    return DepartmentOut(id=d.id, name=d.name, queue_prefix=d.queue_prefix)


def _schedule(s) -> ScheduleOut:  # noqa: ANN001
    return ScheduleOut(id=s.id, doctor_id=s.doctor_id, day_of_week=s.day_of_week, start_time=s.start_time,
                       end_time=s.end_time, valid_from=s.valid_from, valid_to=s.valid_to)


def _time_off(t) -> TimeOffOut:  # noqa: ANN001
    return TimeOffOut(id=t.id, doctor_id=t.doctor_id, starts_at=t.period.lower, ends_at=t.period.upper,
                      reason=t.reason)


def _member(m: ClinicMembership, u: User) -> MemberOut:
    return MemberOut(membership_id=m.id, user_id=u.id, full_name=u.full_name, email=u.email, role=m.role,
                     is_active=m.is_active)


# ------------------------------------------------------------------- settings
@router.patch("", response_model=ClinicDetail)
def update_clinic(body: ClinicUpdate, request: Request, tenant: TenantContext = Depends(ADMIN),
                  db: Session = Depends(get_db)) -> ClinicDetail:
    return clinic_detail(_svc(db, tenant, request).update_clinic(body))


# ---------------------------------------------------------------- departments
@router.get("/departments", response_model=Page[DepartmentOut])
def list_departments(request: Request, limit: int = 50, offset: int = 0, tenant: TenantContext = Depends(ANY_MEMBER),
                     db: Session = Depends(get_db)) -> Page[DepartmentOut]:
    items, total, limit, offset = _svc(db, tenant, request).list_departments(limit, offset)
    return Page(items=[_dept(d) for d in items], total=total, limit=limit, offset=offset)


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(body: DepartmentCreate, request: Request, tenant: TenantContext = Depends(ADMIN),
                      db: Session = Depends(get_db)) -> DepartmentOut:
    return _dept(_svc(db, tenant, request).create_department(body))


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def rename_department(department_id: uuid.UUID, body: DepartmentUpdate, request: Request,
                      tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> DepartmentOut:
    return _dept(_svc(db, tenant, request).rename_department(department_id, body.name))


@router.delete("/departments/{department_id}", status_code=204)
def delete_department(department_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(ADMIN),
                      db: Session = Depends(get_db)) -> Response:
    _svc(db, tenant, request).delete_department(department_id)
    return Response(status_code=204)


# -------------------------------------------------------------------- doctors
@router.get("/doctors", response_model=Page[DoctorOut])
def list_doctors(request: Request, department_id: uuid.UUID | None = None, include_inactive: bool = False,
                 limit: int = 20, offset: int = 0, tenant: TenantContext = Depends(ANY_MEMBER),
                 db: Session = Depends(get_db)) -> Page[DoctorOut]:
    items, total, limit, offset = _svc(db, tenant, request).list_doctors(
        department_id=department_id, include_inactive=include_inactive, limit=limit, offset=offset)
    return Page(items=[DoctorOut.from_model(d) for d in items], total=total, limit=limit, offset=offset)


@router.post("/doctors", response_model=DoctorOut, status_code=201)
def create_doctor(body: DoctorCreate, request: Request, tenant: TenantContext = Depends(ADMIN),
                  db: Session = Depends(get_db)) -> DoctorOut:
    return DoctorOut.from_model(_svc(db, tenant, request).create_doctor(body))


@router.get("/doctors/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(ANY_MEMBER),
               db: Session = Depends(get_db)) -> DoctorOut:
    return DoctorOut.from_model(_svc(db, tenant, request).get_doctor(doctor_id))


@router.patch("/doctors/{doctor_id}", response_model=DoctorOut)
def update_doctor(doctor_id: uuid.UUID, body: DoctorUpdate, request: Request, tenant: TenantContext = Depends(ADMIN),
                  db: Session = Depends(get_db)) -> DoctorOut:
    return DoctorOut.from_model(_svc(db, tenant, request).update_doctor(doctor_id, body))


@router.post("/doctors/{doctor_id}/status", response_model=DoctorOut)
def set_doctor_status(doctor_id: uuid.UUID, body: DoctorStatusUpdate, request: Request,
                      tenant: TenantContext = Depends(STATUS_EDITORS), db: Session = Depends(get_db)) -> DoctorOut:
    return DoctorOut.from_model(_svc(db, tenant, request).set_doctor_status(doctor_id, body))


# ------------------------------------------------------------------ schedules
@router.get("/doctors/{doctor_id}/schedules", response_model=list[ScheduleOut])
def list_schedules(doctor_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(ANY_MEMBER),
                   db: Session = Depends(get_db)) -> list[ScheduleOut]:
    return [_schedule(s) for s in _svc(db, tenant, request).list_schedules(doctor_id)]


@router.post("/doctors/{doctor_id}/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(doctor_id: uuid.UUID, body: ScheduleCreate, request: Request,
                    tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> ScheduleOut:
    return _schedule(_svc(db, tenant, request).create_schedule(doctor_id, body))


@router.delete("/doctors/{doctor_id}/schedules/{schedule_id}", status_code=204)
def delete_schedule(doctor_id: uuid.UUID, schedule_id: uuid.UUID, request: Request,
                    tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> Response:
    _svc(db, tenant, request).delete_schedule(doctor_id, schedule_id)
    return Response(status_code=204)


# -------------------------------------------------------------------- time off
@router.get("/doctors/{doctor_id}/time-off", response_model=list[TimeOffOut])
def list_time_off(doctor_id: uuid.UUID, request: Request, upcoming_only: bool = True,
                  tenant: TenantContext = Depends(STAFF), db: Session = Depends(get_db)) -> list[TimeOffOut]:
    return [_time_off(t) for t in _svc(db, tenant, request).list_time_off(doctor_id, upcoming_only)]


@router.post("/doctors/{doctor_id}/time-off", response_model=TimeOffOut, status_code=201)
def create_time_off(doctor_id: uuid.UUID, body: TimeOffCreate, request: Request,
                    tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> TimeOffOut:
    return _time_off(_svc(db, tenant, request).create_time_off(doctor_id, body))


@router.delete("/doctors/{doctor_id}/time-off/{time_off_id}", status_code=204)
def delete_time_off(doctor_id: uuid.UUID, time_off_id: uuid.UUID, request: Request,
                    tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> Response:
    _svc(db, tenant, request).delete_time_off(doctor_id, time_off_id)
    return Response(status_code=204)


# --------------------------------------------------------------------- members
@router.patch("/members/{membership_id}", response_model=MemberOut)
def update_member(membership_id: uuid.UUID, body: MemberUpdate, request: Request,
                  tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> MemberOut:
    membership, user = _svc(db, tenant, request).set_member_active(membership_id, body.is_active)
    return _member(membership, user)
