"""Simulation lab (clinic admins only): synthetic what-if runs. Reads and writes no clinic data."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import TenantContext, require_clinic_role
from app.api.limits import SIMULATION
from app.permissions.roles import ClinicRole
from app.schemas.simulation import SimulationIn, SimulationOut
from app.services.simulation_service import simulate

router = APIRouter(prefix="/clinics/{clinic_id}/simulation", tags=["simulation"], dependencies=[Depends(SIMULATION)])
ADMIN = require_clinic_role(ClinicRole.CLINIC_ADMIN)


@router.post("", response_model=SimulationOut)
def run_simulation(body: SimulationIn, tenant: TenantContext = Depends(ADMIN)) -> SimulationOut:
    """Compare up to 3 scenarios (e.g. baseline vs "walk-ins double"); deltas are relative to the first."""
    return simulate(body)
