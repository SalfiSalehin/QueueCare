"""Clinic management: settings, departments, doctors, schedules, time off, staff memberships.

Every query is filtered by the tenant's clinic_id explicitly. PostgreSQL RLS is a second,
independent layer, so a bug here still cannot cross tenants. Identifiers supplied by the
client (department_id, doctor_id, ...) are always looked up WITHIN the current clinic, so an
id belonging to another clinic is indistinguishable from one that does not exist (404).
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.errors import ServiceError
from app.models import (
    Clinic,
    ClinicMembership,
    Department,
    Doctor,
    DoctorSchedule,
    DoctorTimeOff,
    User,
)
from app.permissions.roles import ClinicRole, DoctorStatus
from app.schemas.clinic import ClinicSettings, ClinicUpdate
from app.schemas.clinic_ops import (
    DepartmentCreate,
    DoctorCreate,
    DoctorStatusUpdate,
    DoctorUpdate,
    ScheduleCreate,
    TimeOffCreate,
)
from app.services.audit_service import record_audit


def schedules_overlap(
    a_start: time, a_end: time, a_from: date | None, a_to: date | None,
    b_start: time, b_end: time, b_from: date | None, b_to: date | None,
) -> bool:
    """Two windows on the SAME weekday conflict if their times overlap and their validity
    date ranges (open-ended when None) overlap. Touching edges (09:00-12:00 / 12:00-15:00) do not."""
    times = a_start < b_end and b_start < a_end
    dates = (a_from or date.min) <= (b_to or date.max) and (b_from or date.min) <= (a_to or date.max)
    return times and dates


class ClinicAdminService:
    def __init__(self, db: Session, tenant: TenantContext, ip: str | None) -> None:
        self.db = db
        self.tenant = tenant
        self.clinic_id: uuid.UUID = tenant.clinic.id
        self.actor_id: uuid.UUID = tenant.user.id
        self.ip = ip

    # ---------------------------------------------------------------- helpers
    def _audit(self, action: str, entity_type: str, entity_id: uuid.UUID, **meta: Any) -> None:
        record_audit(self.db, action=action, actor_user_id=self.actor_id, clinic_id=self.clinic_id,
                     entity_type=entity_type, entity_id=entity_id, ip=self.ip, metadata=meta)

    def _page(self, stmt: Select[Any], limit: int, offset: int) -> tuple[list[Any], int, int, int]:
        limit, offset = max(1, min(limit, 100)), max(0, offset)
        total = self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        return list(self.db.scalars(stmt.limit(limit).offset(offset))), total, limit, offset

    def _department(self, department_id: uuid.UUID) -> Department:
        dept = self.db.scalar(select(Department).where(Department.id == department_id,
                                                       Department.clinic_id == self.clinic_id))
        if dept is None:
            raise ServiceError(404, "Department not found.")
        return dept

    def _doctor(self, doctor_id: uuid.UUID, *, lock: bool = False) -> Doctor:
        stmt = select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == self.clinic_id)
        if lock:
            stmt = stmt.with_for_update()
        doctor = self.db.scalar(stmt)
        if doctor is None:
            raise ServiceError(404, "Doctor not found.")
        return doctor

    def _commit_or_conflict(self, message: str) -> None:
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ServiceError(409, message) from None

    # --------------------------------------------------------------- settings
    def update_clinic(self, data: ClinicUpdate) -> Clinic:
        clinic = self.db.get(Clinic, self.clinic_id)
        assert clinic is not None  # resolved by the tenant dependency
        changed: list[str] = []
        if data.name is not None and data.name != clinic.name:
            clinic.name = data.name
            changed.append("name")
        if data.timezone is not None and data.timezone != clinic.timezone:
            clinic.timezone = data.timezone
            changed.append("timezone")
        if data.settings is not None:
            # Merge: only fields the client actually sent change; everything else keeps its current value.
            current = ClinicSettings.model_validate(clinic.settings or {})
            merged = current.model_copy(update=data.settings.model_dump(exclude_unset=True))
            if merged != current:
                clinic.settings = merged.model_dump()
                changed.append("settings")
        if changed:
            self._audit("clinic.updated", "clinic", clinic.id, fields=changed)
            self.db.commit()
        return clinic

    # ------------------------------------------------------------ departments
    def list_departments(self, limit: int, offset: int):
        stmt = select(Department).where(Department.clinic_id == self.clinic_id).order_by(Department.name)
        return self._page(stmt, limit, offset)

    def create_department(self, data: DepartmentCreate) -> Department:
        dept = Department(id=uuid.uuid4(), clinic_id=self.clinic_id, name=data.name, queue_prefix=data.queue_prefix)
        self.db.add(dept)
        self._audit("department.created", "department", dept.id, name=data.name, prefix=data.queue_prefix)
        self._commit_or_conflict("A department with that name or queue prefix already exists.")
        return dept

    def rename_department(self, department_id: uuid.UUID, name: str) -> Department:
        dept = self._department(department_id)
        dept.name = name
        self._audit("department.renamed", "department", dept.id, name=name)
        self._commit_or_conflict("A department with that name already exists.")
        return dept

    def delete_department(self, department_id: uuid.UUID) -> None:
        dept = self._department(department_id)
        in_use = self.db.scalar(select(func.count()).select_from(Doctor).where(
            Doctor.clinic_id == self.clinic_id, Doctor.department_id == dept.id))
        if in_use:
            raise ServiceError(409, "Move or deactivate this department's doctors before deleting it.")
        self.db.delete(dept)
        self._audit("department.deleted", "department", dept.id, name=dept.name)
        self.db.commit()

    # ---------------------------------------------------------------- doctors
    def list_doctors(self, *, department_id: uuid.UUID | None, include_inactive: bool, limit: int, offset: int):
        stmt = select(Doctor).where(Doctor.clinic_id == self.clinic_id).order_by(Doctor.display_name, Doctor.id)
        if department_id:
            stmt = stmt.where(Doctor.department_id == department_id)
        if not (include_inactive and self.tenant.role == ClinicRole.CLINIC_ADMIN):
            stmt = stmt.where(Doctor.is_active.is_(True))
        return self._page(stmt, limit, offset)

    def get_doctor(self, doctor_id: uuid.UUID) -> Doctor:
        doctor = self._doctor(doctor_id)
        if not doctor.is_active and self.tenant.role != ClinicRole.CLINIC_ADMIN:
            raise ServiceError(404, "Doctor not found.")
        return doctor

    def _check_linkable_user(self, user_id: uuid.UUID, exclude_doctor: uuid.UUID | None = None) -> None:
        is_doctor_member = self.db.scalar(select(ClinicMembership.id).where(
            ClinicMembership.clinic_id == self.clinic_id, ClinicMembership.user_id == user_id,
            ClinicMembership.role == ClinicRole.DOCTOR, ClinicMembership.is_active.is_(True)))
        if not is_doctor_member:
            raise ServiceError(422, "That user is not an active DOCTOR member of this clinic.")
        stmt = select(Doctor.id).where(Doctor.clinic_id == self.clinic_id, Doctor.user_id == user_id)
        if exclude_doctor:
            stmt = stmt.where(Doctor.id != exclude_doctor)
        if self.db.scalar(stmt):
            raise ServiceError(409, "That user already has a doctor profile in this clinic.")

    def create_doctor(self, data: DoctorCreate) -> Doctor:
        self._department(data.department_id)
        if data.user_id:
            self._check_linkable_user(data.user_id)
        doctor = Doctor(
            id=uuid.uuid4(), clinic_id=self.clinic_id, department_id=data.department_id, user_id=data.user_id,
            display_name=data.display_name, default_slot_minutes=data.default_slot_minutes,
            buffer_minutes=data.buffer_minutes, status=DoctorStatus.AVAILABLE.value,
            current_delay_minutes=0, is_active=True,
        )
        self.db.add(doctor)
        self._audit("doctor.created", "doctor", doctor.id, department_id=str(data.department_id),
                    linked_account=data.user_id is not None)
        self._commit_or_conflict("That user already has a doctor profile in this clinic.")
        return doctor

    def update_doctor(self, doctor_id: uuid.UUID, data: DoctorUpdate) -> Doctor:
        doctor = self._doctor(doctor_id, lock=True)
        changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if "department_id" in changes:
            self._department(changes["department_id"])
        for key, value in changes.items():
            setattr(doctor, key, value)
        if changes:
            self._audit("doctor.updated", "doctor", doctor.id, fields=sorted(changes))
            self.db.commit()
        return doctor

    def set_doctor_status(self, doctor_id: uuid.UUID, data: DoctorStatusUpdate) -> Doctor:
        doctor = self._doctor(doctor_id, lock=True)
        # A doctor may only change their OWN availability; admins and receptionists may change any.
        if self.tenant.role == ClinicRole.DOCTOR and doctor.user_id != self.actor_id:
            raise ServiceError(403, "You can only update your own status.")
        if not doctor.is_active:
            raise ServiceError(409, "This doctor is deactivated.")
        previous = doctor.status
        doctor.status = data.status.value
        doctor.current_delay_minutes = data.current_delay_minutes
        self._audit("doctor.status_changed", "doctor", doctor.id, previous=previous, status=data.status.value,
                    delay_minutes=data.current_delay_minutes)
        self.db.commit()
        return doctor

    # -------------------------------------------------------------- schedules
    def list_schedules(self, doctor_id: uuid.UUID) -> list[DoctorSchedule]:
        self.get_doctor(doctor_id)
        return list(self.db.scalars(select(DoctorSchedule).where(
            DoctorSchedule.clinic_id == self.clinic_id, DoctorSchedule.doctor_id == doctor_id,
        ).order_by(DoctorSchedule.day_of_week, DoctorSchedule.start_time)))

    def create_schedule(self, doctor_id: uuid.UUID, data: ScheduleCreate) -> DoctorSchedule:
        self._doctor(doctor_id, lock=True)  # serialises concurrent schedule edits for this doctor
        existing = self.db.scalars(select(DoctorSchedule).where(
            DoctorSchedule.clinic_id == self.clinic_id, DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == data.day_of_week))
        for row in existing:
            if schedules_overlap(data.start_time, data.end_time, data.valid_from, data.valid_to,
                                 row.start_time, row.end_time, row.valid_from, row.valid_to):
                raise ServiceError(409, "This window overlaps an existing schedule for that day.")
        schedule = DoctorSchedule(id=uuid.uuid4(), clinic_id=self.clinic_id, doctor_id=doctor_id,
                                  day_of_week=data.day_of_week, start_time=data.start_time, end_time=data.end_time,
                                  valid_from=data.valid_from, valid_to=data.valid_to)
        self.db.add(schedule)
        self._audit("schedule.created", "doctor", doctor_id, day=data.day_of_week,
                    start=data.start_time.isoformat(), end=data.end_time.isoformat())
        # The DB exclusion constraint is the final authority if two requests race past the check above.
        self._commit_or_conflict("This window overlaps an existing schedule for that day.")
        return schedule

    def delete_schedule(self, doctor_id: uuid.UUID, schedule_id: uuid.UUID) -> None:
        self._doctor(doctor_id, lock=True)
        row = self.db.scalar(select(DoctorSchedule).where(
            DoctorSchedule.id == schedule_id, DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.clinic_id == self.clinic_id))
        if row is None:
            raise ServiceError(404, "Schedule not found.")
        self.db.delete(row)
        self._audit("schedule.deleted", "doctor", doctor_id, day=row.day_of_week)
        self.db.commit()

    # --------------------------------------------------------------- time off
    def list_time_off(self, doctor_id: uuid.UUID, upcoming_only: bool) -> list[DoctorTimeOff]:
        self._doctor(doctor_id)
        stmt = select(DoctorTimeOff).where(DoctorTimeOff.clinic_id == self.clinic_id,
                                           DoctorTimeOff.doctor_id == doctor_id)
        if upcoming_only:
            stmt = stmt.where(func.upper(DoctorTimeOff.period) > datetime.now(UTC))
        return list(self.db.scalars(stmt.order_by(func.lower(DoctorTimeOff.period))))

    def create_time_off(self, doctor_id: uuid.UUID, data: TimeOffCreate) -> DoctorTimeOff:
        self._doctor(doctor_id, lock=True)
        start, end = data.as_utc()
        row = DoctorTimeOff(id=uuid.uuid4(), clinic_id=self.clinic_id, doctor_id=doctor_id,
                            period=Range(start, end, bounds="[)"), reason=data.reason)
        self.db.add(row)
        self._audit("time_off.created", "doctor", doctor_id, starts_at=start.isoformat(), ends_at=end.isoformat())
        self.db.commit()
        return row

    def delete_time_off(self, doctor_id: uuid.UUID, time_off_id: uuid.UUID) -> None:
        self._doctor(doctor_id, lock=True)
        row = self.db.scalar(select(DoctorTimeOff).where(
            DoctorTimeOff.id == time_off_id, DoctorTimeOff.doctor_id == doctor_id,
            DoctorTimeOff.clinic_id == self.clinic_id))
        if row is None:
            raise ServiceError(404, "Time off not found.")
        self.db.delete(row)
        self._audit("time_off.deleted", "doctor", doctor_id)
        self.db.commit()

    # ---------------------------------------------------------------- members
    def set_member_active(self, membership_id: uuid.UUID, active: bool) -> tuple[ClinicMembership, User]:
        # Lock the clinic row so two admins cannot deactivate each other at the same moment.
        self.db.scalar(select(Clinic.id).where(Clinic.id == self.clinic_id).with_for_update())
        membership = self.db.scalar(select(ClinicMembership).where(
            ClinicMembership.id == membership_id, ClinicMembership.clinic_id == self.clinic_id))
        if membership is None:
            raise ServiceError(404, "Member not found.")
        if membership.is_active == active:
            user = self.db.get(User, membership.user_id)
            assert user is not None
            return membership, user
        if not active and membership.role == ClinicRole.CLINIC_ADMIN:
            other_admins = self.db.scalar(select(func.count()).select_from(ClinicMembership).where(
                ClinicMembership.clinic_id == self.clinic_id, ClinicMembership.role == ClinicRole.CLINIC_ADMIN,
                ClinicMembership.is_active.is_(True), ClinicMembership.id != membership.id))
            if not other_admins:
                self.db.rollback()
                raise ServiceError(409, "A clinic must keep at least one active administrator.")
        membership.is_active = active
        self._audit("member.activated" if active else "member.deactivated", "user", membership.user_id,
                    role=membership.role)
        self.db.commit()
        user = self.db.get(User, membership.user_id)
        assert user is not None
        return membership, user
