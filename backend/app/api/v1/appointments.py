"""Appointment, slot and patient endpoints. Thin: authorization via dependencies, logic in the service."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, require_clinic_role
from app.api.limits import BOOKING
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.ratelimit import get_client_ip
from app.permissions.roles import AppointmentStatus, ClinicRole
from app.schemas.appointments import (
    AlternativesOut, AppointmentCancel, AppointmentCreate, AppointmentOut, AppointmentReschedule, PatientCreate,
    PatientOut, SlotOut,
)
from app.schemas.common import Page
from app.services.appointment_service import AppointmentService

router = APIRouter(prefix="/clinics/{clinic_id}", tags=["appointments"])

ANY_MEMBER = require_clinic_role(*ClinicRole)
FRONT_DESK = require_clinic_role(ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST)
BOOKERS = require_clinic_role(ClinicRole.PATIENT, ClinicRole.RECEPTIONIST, ClinicRole.CLINIC_ADMIN)


def _svc(request: Request, tenant: TenantContext, db: Session, settings: Settings) -> AppointmentService:
    return AppointmentService(db, tenant, ip=get_client_ip(request, settings))


# ---------------------------------------------------------------------- slots
@router.get("/doctors/{doctor_id}/slots", response_model=list[SlotOut])
def doctor_slots(doctor_id: uuid.UUID, request: Request, from_: date | None = Query(default=None, alias="from"),
                 to: date | None = None, tenant: TenantContext = Depends(ANY_MEMBER),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[SlotOut]:
    """Bookable start times (UTC, plus clinic-local) for one doctor. Dates are clinic-local dates."""
    return _svc(request, tenant, db, settings).available_slots(doctor_id, from_, to)


@router.get("/doctors/{doctor_id}/alternatives", response_model=AlternativesOut)
def doctor_alternatives(doctor_id: uuid.UUID, request: Request, from_: date | None = Query(default=None, alias="from"),
                        to: date | None = None, limit: int = Query(default=5, ge=1, le=10),
                        tenant: TenantContext = Depends(ANY_MEMBER), db: Session = Depends(get_db),
                        settings: Settings = Depends(get_settings)) -> AlternativesOut:
    """If this doctor is fully booked (or just to compare), which other doctors have the earliest slots.
    Default window: the next 14 days. Reserves nothing: book through the normal endpoint."""
    return _svc(request, tenant, db, settings).alternatives(doctor_id, from_, to, limit)


# --------------------------------------------------------------- appointments
@router.post("/appointments", response_model=AppointmentOut, status_code=201, dependencies=[Depends(BOOKING)])
def book(body: AppointmentCreate, request: Request, tenant: TenantContext = Depends(BOOKERS),
         db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> AppointmentOut:
    return _svc(request, tenant, db, settings).book(body)


@router.get("/appointments", response_model=Page[AppointmentOut])
def list_appointments(
    request: Request, doctor_id: uuid.UUID | None = None, status: AppointmentStatus | None = None,
    on_date: date | None = Query(default=None, alias="date"), patient_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(ANY_MEMBER), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Page[AppointmentOut]:
    """Patients see their own appointments, doctors their own schedule, front-desk staff the clinic's."""
    return _svc(request, tenant, db, settings).list(
        doctor_id=doctor_id, status=status, on_date=on_date, patient_id=patient_id, limit=limit, offset=offset)


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def get_appointment(appointment_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(ANY_MEMBER),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> AppointmentOut:
    return _svc(request, tenant, db, settings).get(appointment_id)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(appointment_id: uuid.UUID, request: Request, body: AppointmentCancel | None = None,
                       tenant: TenantContext = Depends(ANY_MEMBER), db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings)) -> AppointmentOut:
    return _svc(request, tenant, db, settings).cancel(appointment_id, body.reason if body else None)


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(appointment_id: uuid.UUID, body: AppointmentReschedule, request: Request,
                           tenant: TenantContext = Depends(BOOKERS), db: Session = Depends(get_db),
                           settings: Settings = Depends(get_settings)) -> AppointmentOut:
    return _svc(request, tenant, db, settings).reschedule(appointment_id, body)


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentOut)
def confirm_appointment(appointment_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(FRONT_DESK),
                        db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> AppointmentOut:
    return _svc(request, tenant, db, settings).confirm(appointment_id)


# ------------------------------------------------------------------- patients
@router.post("/patients", response_model=PatientOut, status_code=201)
def create_patient(body: PatientCreate, request: Request, tenant: TenantContext = Depends(FRONT_DESK),
                   db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> PatientOut:
    """Register a patient (e.g. a walk-in without an account). Staff only."""
    return _svc(request, tenant, db, settings).create_patient(body)


@router.get("/patients", response_model=Page[PatientOut])
def search_patients(request: Request, q: str | None = Query(default=None, min_length=2, max_length=100),
                    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
                    tenant: TenantContext = Depends(FRONT_DESK), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)) -> Page[PatientOut]:
    return _svc(request, tenant, db, settings).list_patients(q, limit, offset)
