"""Live queue endpoints. Thin: authorization via dependencies, rules in QueueService."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, require_clinic_role
from app.api.limits import QUEUE_WRITE
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.ratelimit import get_client_ip
from app.permissions.roles import ClinicRole
from app.schemas.queue import EstimateOut, MyTokenOut, QueueBoard, TokenEventOut, TokenOut, TransitionBody, WalkInCreate
from app.services.queue_logic import QueueAction
from app.services.queue_service import QueueService

router = APIRouter(prefix="/clinics/{clinic_id}", tags=["queue"])

FRONT_DESK = require_clinic_role(ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST)
STAFF = require_clinic_role(ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST, ClinicRole.DOCTOR)
PATIENT_ONLY = require_clinic_role(ClinicRole.PATIENT)
ANY_MEMBER = require_clinic_role(*ClinicRole)


def _svc(request: Request, tenant: TenantContext, db: Session, settings: Settings) -> QueueService:
    return QueueService(db, tenant, ip=get_client_ip(request, settings))


@router.post("/queue/walk-ins", response_model=TokenOut, status_code=201, dependencies=[Depends(QUEUE_WRITE)])
def add_walk_in(body: WalkInCreate, request: Request, tenant: TenantContext = Depends(FRONT_DESK),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> TokenOut:
    """Put a registered patient into a doctor's queue (front desk)."""
    return _svc(request, tenant, db, settings).walk_in(body)


@router.post("/appointments/{appointment_id}/check-in", response_model=TokenOut, status_code=201)
def check_in(appointment_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(FRONT_DESK),
             db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> TokenOut:
    """Check a booked patient in on the day of the appointment; creates their queue token."""
    return _svc(request, tenant, db, settings).check_in(appointment_id)


@router.get("/doctors/{doctor_id}/queue", response_model=QueueBoard)
def queue_board(doctor_id: uuid.UUID, request: Request, on_date: date | None = None,
                tenant: TenantContext = Depends(STAFF), db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings)) -> QueueBoard:
    """One doctor's queue: serving now, waiting in call order, skipped. Doctors see only their own."""
    return _svc(request, tenant, db, settings).board(doctor_id, on_date)


@router.post("/doctors/{doctor_id}/queue/call-next", response_model=TokenOut)
def call_next(doctor_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(STAFF),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> TokenOut:
    return _svc(request, tenant, db, settings).call_next(doctor_id)


@router.get("/queue/mine", response_model=list[MyTokenOut])
def my_tokens(request: Request, tenant: TenantContext = Depends(PATIENT_ONLY), db: Session = Depends(get_db),
              settings: Settings = Depends(get_settings)) -> list[MyTokenOut]:
    """A patient's own tokens today and how many people are ahead. Never exposes other patients."""
    return _svc(request, tenant, db, settings).mine()


@router.get("/queue/tokens/{token_id}", response_model=TokenOut)
def get_token(token_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(STAFF),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> TokenOut:
    return _svc(request, tenant, db, settings).get_token(token_id)


@router.get("/queue/tokens/{token_id}/events", response_model=list[TokenEventOut])
def token_events(token_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(STAFF),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[TokenEventOut]:
    return _svc(request, tenant, db, settings).events(token_id)


@router.get("/queue/tokens/{token_id}/estimate", response_model=EstimateOut)
def estimate(token_id: uuid.UUID, request: Request, tenant: TenantContext = Depends(ANY_MEMBER),
             db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> EstimateOut:
    """Estimated remaining wait. Patients get the median only; staff and doctors also get the range."""
    return _svc(request, tenant, db, settings).estimate(token_id)


@router.post("/queue/tokens/{token_id}/{action}", response_model=TokenOut)
def transition(token_id: uuid.UUID, action: QueueAction, request: Request, body: TransitionBody | None = None,
               tenant: TenantContext = Depends(ANY_MEMBER), db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)) -> TokenOut:
    """call | start | complete | skip | requeue | no-show | cancel. Role and state rules are in the service."""
    return _svc(request, tenant, db, settings).act(token_id, action, body)
