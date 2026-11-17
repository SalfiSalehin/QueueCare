"""Clinic analytics (read-only, clinic admins only). Counts and statistics; no patient identities."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, require_clinic_role
from app.api.limits import ANALYTICS
from app.core.database import get_db
from app.permissions.roles import ClinicRole
from app.schemas.analytics import (
    DoctorUtilisationOut, DriftOut, LoadOut, OverviewOut, PredictionAccuracyOut, SchedulingSuggestionsOut,
)
from app.services.analytics_service import AnalyticsService
from app.services.drift_service import DriftService
from app.services.scheduling_service import SchedulingService

router = APIRouter(prefix="/clinics/{clinic_id}/analytics", tags=["analytics"], dependencies=[Depends(ANALYTICS)])
ADMIN = require_clinic_role(ClinicRole.CLINIC_ADMIN)


@router.get("/overview", response_model=OverviewOut)
def overview(start_date: date | None = None, end_date: date | None = None,
             tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> OverviewOut:
    """Dates are clinic-local and inclusive; default is the last 30 days; at most 366 days."""
    return AnalyticsService(db, tenant).overview(start_date, end_date)


@router.get("/doctors", response_model=DoctorUtilisationOut)
def doctors(start_date: date | None = None, end_date: date | None = None,
            tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> DoctorUtilisationOut:
    return AnalyticsService(db, tenant).doctors(start_date, end_date)


@router.get("/load", response_model=LoadOut)
def load(start_date: date | None = None, end_date: date | None = None,
         tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> LoadOut:
    return AnalyticsService(db, tenant).load(start_date, end_date)


@router.get("/prediction-accuracy", response_model=PredictionAccuracyOut)
def prediction_accuracy(start_date: date | None = None, end_date: date | None = None,
                        tenant: TenantContext = Depends(ADMIN), db: Session = Depends(get_db)) -> PredictionAccuracyOut:
    return AnalyticsService(db, tenant).prediction_accuracy(start_date, end_date)


@router.get("/drift", response_model=DriftOut)
def drift(days: int = Query(14, ge=1, le=90), tenant: TenantContext = Depends(ADMIN),
          db: Session = Depends(get_db)) -> DriftOut:
    """Has the model's input (or error) drifted from what it was trained on? Alarm, not verdict."""
    return DriftService(db, tenant).report(days)


@router.get("/scheduling-suggestions", response_model=SchedulingSuggestionsOut)
def scheduling_suggestions(days: int = Query(90, ge=7, le=365), tenant: TenantContext = Depends(ADMIN),
                           db: Session = Depends(get_db)) -> SchedulingSuggestionsOut:
    """Per-doctor slot-length advice from completed consultations. Advice only; changes nothing."""
    return SchedulingService(db, tenant).suggestions(days)
