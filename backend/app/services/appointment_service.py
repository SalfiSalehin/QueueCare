"""Appointment business logic: slots, booking, cancelling, rescheduling, confirming, patients.

Concurrency model
- Two people can both see a slot as free and both try to book it. The database exclusion
  constraint `appointments_no_doctor_overlap` is the authority: one INSERT wins, the other fails
  with SQLSTATE 23P01, which we map to HTTP 409. Application checks only give friendlier errors.
- Reschedule is one transaction: free the old slot, claim the new one, commit. Any failure rolls
  back everything, so a patient never ends up with zero or two appointments.
- Rows being modified are locked (FOR UPDATE) so two staff members cannot act on one appointment
  at the same time.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.errors import ServiceError
from app.models import Appointment, Doctor, DoctorSchedule, DoctorTimeOff, Patient
from app.permissions.roles import (
    ACTIVE_APPOINTMENT_STATUSES, AppointmentStatus, ClinicRole, DoctorStatus,
)
from app.schemas.appointments import (
    AlternativesOut, AppointmentCreate, AppointmentOut, AppointmentReschedule, DoctorAvailability, PatientCreate,
    PatientOut, SlotOut,
)
from app.schemas.clinic import ClinicSettings
from app.schemas.common import Page
from app.services.audit_service import record_audit
from app.services.notification_service import notify_appointment
from app.services.realtime_events import appointment_changed
from app.services.slots import Slot, Window, compute_slots, day_bounds_utc

EXCLUSION_VIOLATION = "23P01"
MAX_ALTERNATIVE_CANDIDATES = 25
MAX_ACTIVE_PER_PATIENT = 5      # abuse guard: one patient cannot hoard a doctor's whole day
MAX_SLOT_RANGE_DAYS = 14
STAFF_BOOKERS = (ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST)
_ACTIVE = [s.value for s in ACTIVE_APPOINTMENT_STATUSES]
_CANCELLABLE = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED, AppointmentStatus.CHECKED_IN}
_MOVABLE = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}


def _sqlstate(exc: IntegrityError) -> str | None:
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


class AppointmentService:
    def __init__(self, db: Session, tenant: TenantContext, ip: str | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.tenant = tenant
        self.ip = ip
        self._now = now or (lambda: datetime.now(UTC))
        self.clinic_id = tenant.clinic.id
        self.actor_id = tenant.user.id
        self.role = tenant.role
        self.settings = ClinicSettings.model_validate(tenant.clinic.settings or {})
        self.tz = ZoneInfo(tenant.clinic.timezone)

    # ------------------------------------------------------------------ helpers
    def _audit(self, action: str, entity_id: uuid.UUID, **meta: Any) -> None:
        record_audit(self.db, action=action, actor_user_id=self.actor_id, clinic_id=self.clinic_id,
                     entity_type="appointment", entity_id=entity_id, ip=self.ip, metadata=meta)

    def _emit(self, appt: Appointment, change: str, patient_user_id: uuid.UUID | None | str = "lookup") -> None:
        if patient_user_id == "lookup":
            patient_user_id = self.db.scalar(select(Patient.user_id).where(
                Patient.id == appt.patient_id, Patient.clinic_id == self.clinic_id))
        appointment_changed(self.db, clinic_id=self.clinic_id, appointment=appt,
                            patient_user_id=patient_user_id, change=change)  # type: ignore[arg-type]

    def _flush(self, conflict_message: str) -> None:
        """Send pending changes to the database now, with the same conflict handling as `_commit`.

        Called before anything that opens a savepoint (notifications): a savepoint flushes first, and a
        constraint violation from THIS request's own changes must become the normal 409, not be mistaken
        for a notification problem."""
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if _sqlstate(exc) == EXCLUSION_VIOLATION:
                raise ServiceError(409, conflict_message) from None
            raise

    def _commit(self, conflict_message: str) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if _sqlstate(exc) == EXCLUSION_VIOLATION:
                raise ServiceError(409, conflict_message) from None
            raise

    def _doctor(self, doctor_id: uuid.UUID) -> Doctor:
        doctor = self.db.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == self.clinic_id))
        if doctor is None or not doctor.is_active:
            raise ServiceError(404, "Doctor not found.")
        return doctor

    # --------------------------------------------------------------------- slots
    def _slots(self, doctor: Doctor, from_date: date, to_date: date, *,
               exclude_id: uuid.UUID | None = None, ignore_busy: bool = False) -> list[Slot]:
        windows = [Window(s.day_of_week, s.start_time, s.end_time, s.valid_from, s.valid_to)
                   for s in self.db.scalars(select(DoctorSchedule).where(
                       DoctorSchedule.doctor_id == doctor.id, DoctorSchedule.clinic_id == self.clinic_id))]
        range_start, range_end = day_bounds_utc(from_date, to_date, self.tz)
        busy: list[tuple[datetime, datetime]] = []
        if not ignore_busy:
            low, high = datetime.min.replace(tzinfo=UTC), datetime.max.replace(tzinfo=UTC)
            for off in self.db.scalars(select(DoctorTimeOff).where(
                    DoctorTimeOff.doctor_id == doctor.id, DoctorTimeOff.clinic_id == self.clinic_id,
                    func.upper(DoctorTimeOff.period) > range_start, func.lower(DoctorTimeOff.period) < range_end)):
                busy.append((off.period.lower or low, off.period.upper or high))
            stmt = select(Appointment.starts_at, Appointment.ends_at).where(
                Appointment.doctor_id == doctor.id, Appointment.clinic_id == self.clinic_id,
                Appointment.status.in_(_ACTIVE), Appointment.starts_at < range_end, Appointment.ends_at > range_start)
            if exclude_id:
                stmt = stmt.where(Appointment.id != exclude_id)
            busy.extend((a, b) for a, b in self.db.execute(stmt))
        now = self._now()
        return compute_slots(
            windows=windows, tz=self.tz, from_date=from_date, to_date=to_date,
            slot_minutes=doctor.default_slot_minutes, buffer_minutes=doctor.buffer_minutes, busy=busy,
            earliest=now + timedelta(minutes=self.settings.min_notice_minutes),
            latest=now + timedelta(days=self.settings.booking_horizon_days),
        )

    def available_slots(self, doctor_id: uuid.UUID, from_date: date | None, to_date: date | None) -> list[SlotOut]:
        doctor = self._doctor(doctor_id)
        start = from_date or self._now().astimezone(self.tz).date()
        end = to_date or start + timedelta(days=6)
        if end < start:
            raise ServiceError(422, "'to' must not be before 'from'.")
        if (end - start).days + 1 > MAX_SLOT_RANGE_DAYS:
            raise ServiceError(422, f"Ask for at most {MAX_SLOT_RANGE_DAYS} days at a time.")
        if doctor.status == DoctorStatus.OFF_DUTY:
            return []
        return [SlotOut(starts_at=s.starts_at, ends_at=s.ends_at, starts_at_local=s.starts_at.astimezone(self.tz).isoformat())
                for s in self._slots(doctor, start, end)]

    def alternatives(self, doctor_id: uuid.UUID, from_date: date | None, to_date: date | None,
                     limit: int) -> AlternativesOut:
        """Doctors who could see a patient sooner than (or instead of) the requested one.

        Same department first on ties, then earliest slot. Rules are the normal booking rules (schedules,
        time off, existing appointments, notice period, horizon); nothing is reserved by asking."""
        requested = self._doctor(doctor_id)
        start = from_date or self._now().astimezone(self.tz).date()
        end = to_date or start + timedelta(days=13)
        if end < start:
            raise ServiceError(422, "'to' must not be before 'from'.")
        if (end - start).days + 1 > MAX_SLOT_RANGE_DAYS:
            raise ServiceError(422, f"Ask for at most {MAX_SLOT_RANGE_DAYS} days at a time.")

        def describe(doctor: Doctor) -> DoctorAvailability:
            slots = [] if doctor.status == DoctorStatus.OFF_DUTY else self._slots(doctor, start, end)
            first = slots[0] if slots else None
            return DoctorAvailability(
                doctor_id=doctor.id, display_name=doctor.display_name, department_id=doctor.department_id,
                same_department=doctor.department_id == requested.department_id,
                earliest=None if first is None else SlotOut(
                    starts_at=first.starts_at, ends_at=first.ends_at,
                    starts_at_local=first.starts_at.astimezone(self.tz).isoformat()),
                slots_in_range=len(slots))

        others = self.db.scalars(select(Doctor).where(
            Doctor.clinic_id == self.clinic_id, Doctor.is_active.is_(True), Doctor.id != requested.id)
            .order_by(Doctor.display_name).limit(MAX_ALTERNATIVE_CANDIDATES)).all()
        available = [a for a in (describe(d) for d in others) if a.earliest is not None]
        available.sort(key=lambda a: (a.earliest.starts_at, not a.same_department, a.display_name))  # type: ignore[union-attr]
        return AlternativesOut(requested=describe(requested), alternatives=available[:limit])

    def _require_slot(self, doctor: Doctor, starts_at: datetime, exclude_id: uuid.UUID | None = None) -> Slot:
        """422 if the time is not on the doctor's bookable grid; 409 if it is, but already taken."""
        if doctor.status == DoctorStatus.OFF_DUTY:
            raise ServiceError(409, "This doctor is not accepting bookings right now.")
        day = starts_at.astimezone(self.tz).date()
        grid = self._slots(doctor, day, day, ignore_busy=True)
        slot = next((s for s in grid if s.starts_at == starts_at), None)
        if slot is None:
            raise ServiceError(422, "That is not a bookable time for this doctor.")
        free = self._slots(doctor, day, day, exclude_id=exclude_id)
        if not any(s.starts_at == starts_at for s in free):
            raise ServiceError(409, "That time is no longer available.")
        return slot

    # ------------------------------------------------------------------ patients
    def _own_patient(self, *, create: bool) -> Patient | None:
        stmt = select(Patient).where(Patient.clinic_id == self.clinic_id, Patient.user_id == self.actor_id,
                                     Patient.deleted_at.is_(None))
        patient = self.db.scalar(stmt)
        if patient is None and create:
            fresh = Patient(id=uuid.uuid4(), clinic_id=self.clinic_id, user_id=self.actor_id,
                            full_name=self.tenant.user.full_name, phone=self.tenant.user.phone)
            try:
                with self.db.begin_nested():     # savepoint: a lost race must not poison the transaction
                    self.db.add(fresh)
                    self.db.flush()
                patient = fresh
            except IntegrityError:
                patient = self.db.scalar(stmt)   # a concurrent request created it first
        return patient

    def create_patient(self, data: PatientCreate) -> PatientOut:
        patient = Patient(id=uuid.uuid4(), clinic_id=self.clinic_id, full_name=data.full_name, phone=data.phone,
                          date_of_birth=data.date_of_birth)
        self.db.add(patient)
        record_audit(self.db, action="patient.created", actor_user_id=self.actor_id, clinic_id=self.clinic_id,
                     entity_type="patient", entity_id=patient.id, ip=self.ip)
        self.db.commit()
        return PatientOut(id=patient.id, full_name=patient.full_name, phone=patient.phone,
                          date_of_birth=patient.date_of_birth, has_account=False)

    def list_patients(self, q: str | None, limit: int, offset: int) -> Page[PatientOut]:
        stmt = select(Patient).where(Patient.clinic_id == self.clinic_id, Patient.deleted_at.is_(None))
        if q:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(or_(Patient.full_name.ilike(like, escape="\\"), Patient.phone.ilike(like, escape="\\")))
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(stmt.order_by(Patient.full_name, Patient.id).limit(limit).offset(offset)).all()
        return Page(items=[PatientOut(id=p.id, full_name=p.full_name, phone=p.phone, date_of_birth=p.date_of_birth,
                                      has_account=p.user_id is not None) for p in rows],
                    total=total, limit=limit, offset=offset)

    # ----------------------------------------------------------------- reading
    def _query(self) -> Select[Any]:
        """Appointments visible to the caller. Patients see their own, doctors their own schedule,
        front-desk staff see the clinic. Everything is also fenced by clinic_id (and RLS)."""
        stmt = (
            select(Appointment, Doctor.display_name, Patient.full_name)
            .join(Doctor, and_(Doctor.id == Appointment.doctor_id, Doctor.clinic_id == Appointment.clinic_id))
            .join(Patient, and_(Patient.id == Appointment.patient_id, Patient.clinic_id == Appointment.clinic_id))
            .where(Appointment.clinic_id == self.clinic_id)
        )
        if self.role == ClinicRole.PATIENT:
            stmt = stmt.where(Patient.user_id == self.actor_id)
        elif self.role == ClinicRole.DOCTOR:
            stmt = stmt.where(Doctor.user_id == self.actor_id)
        return stmt

    def _out(self, row: Any) -> AppointmentOut:
        appt, doctor_name, patient_name = row
        return AppointmentOut.build(appt, doctor_name, patient_name, self.tz)

    def get(self, appointment_id: uuid.UUID) -> AppointmentOut:
        row = self.db.execute(self._query().where(Appointment.id == appointment_id)).first()
        if row is None:
            raise ServiceError(404, "Appointment not found.")
        return self._out(row)

    def list(self, *, doctor_id: uuid.UUID | None, status: AppointmentStatus | None, on_date: date | None,
             patient_id: uuid.UUID | None, limit: int, offset: int) -> Page[AppointmentOut]:
        stmt = self._query()
        if doctor_id:
            stmt = stmt.where(Appointment.doctor_id == doctor_id)
        if status:
            stmt = stmt.where(Appointment.status == status.value)
        if patient_id and self.role in STAFF_BOOKERS:
            stmt = stmt.where(Appointment.patient_id == patient_id)
        if on_date:
            start, end = day_bounds_utc(on_date, on_date, self.tz)
            stmt = stmt.where(Appointment.starts_at >= start, Appointment.starts_at < end)
        total = self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        rows = self.db.execute(stmt.order_by(Appointment.starts_at, Appointment.id).limit(limit).offset(offset)).all()
        return Page(items=[self._out(r) for r in rows], total=total, limit=limit, offset=offset)

    def _locked(self, appointment_id: uuid.UUID) -> Appointment:
        row = self.db.execute(
            self._query().where(Appointment.id == appointment_id).with_for_update(of=Appointment)).first()
        if row is None:
            raise ServiceError(404, "Appointment not found.")   # also covers "exists but not yours"
        return row[0]

    # ----------------------------------------------------------------- booking
    def book(self, data: AppointmentCreate) -> AppointmentOut:
        doctor = self._doctor(data.doctor_id)
        if self.role == ClinicRole.PATIENT:
            if data.patient_id is not None:
                raise ServiceError(422, "patient_id is only for staff bookings.")
            patient = self._own_patient(create=True)
            assert patient is not None
            active = self.db.scalar(select(func.count()).select_from(Appointment).where(
                Appointment.clinic_id == self.clinic_id, Appointment.patient_id == patient.id,
                Appointment.status.in_(_ACTIVE), Appointment.starts_at > self._now())) or 0
            if active >= MAX_ACTIVE_PER_PATIENT:
                raise ServiceError(409, f"You can hold at most {MAX_ACTIVE_PER_PATIENT} upcoming appointments.")
        else:
            if data.patient_id is None:
                raise ServiceError(422, "patient_id is required when booking for a patient.")
            patient = self.db.scalar(select(Patient).where(
                Patient.id == data.patient_id, Patient.clinic_id == self.clinic_id, Patient.deleted_at.is_(None)))
            if patient is None:
                raise ServiceError(404, "Patient not found.")

        slot = self._require_slot(doctor, data.starts_at)
        appt = Appointment(id=uuid.uuid4(), clinic_id=self.clinic_id, doctor_id=doctor.id, patient_id=patient.id,
                           starts_at=slot.starts_at, ends_at=slot.occupies_until,
                           status=AppointmentStatus.CONFIRMED.value)
        self.db.add(appt)
        self._audit("appointment.booked", appt.id, doctor_id=str(doctor.id), starts_at=slot.starts_at.isoformat(),
                    by_role=self.role.value)
        self._emit(appt, "booked", patient.user_id)
        self._flush("That time was just taken. Please choose another slot.")
        notify_appointment(self.db, self.tenant, appt, "appointment.booked", patient.user_id)
        self._commit("That time was just taken. Please choose another slot.")
        return self.get(appt.id)

    # ------------------------------------------------------- cancel / reschedule
    def _enforce_patient_cutoff(self, appt: Appointment, action: str) -> None:
        if self.role != ClinicRole.PATIENT:
            return
        cutoff = timedelta(hours=self.settings.cancellation_cutoff_hours)
        if appt.starts_at - self._now() < cutoff:
            raise ServiceError(
                409, f"Appointments can only be {action} online up to {self.settings.cancellation_cutoff_hours} "
                     "hours before the start. Please contact the clinic.")

    def cancel(self, appointment_id: uuid.UUID, reason: str | None) -> AppointmentOut:
        appt = self._locked(appointment_id)
        status = AppointmentStatus(appt.status)
        allowed = _CANCELLABLE if self.role != ClinicRole.PATIENT else _MOVABLE
        if status not in allowed:
            raise ServiceError(409, f"A {status.value.lower().replace('_', ' ')} appointment cannot be cancelled.")
        self._enforce_patient_cutoff(appt, "cancelled")
        appt.status = AppointmentStatus.CANCELLED.value
        appt.cancel_reason = reason
        self._audit("appointment.cancelled", appt.id, by_role=self.role.value, previous_status=status.value)
        self._emit(appt, "cancelled")
        self._flush("This appointment could not be cancelled right now. Please try again.")
        notify_appointment(self.db, self.tenant, appt, "appointment.cancelled")
        self.db.commit()
        return self.get(appt.id)

    def reschedule(self, appointment_id: uuid.UUID, data: AppointmentReschedule) -> AppointmentOut:
        old = self._locked(appointment_id)
        status = AppointmentStatus(old.status)
        if status not in _MOVABLE:
            raise ServiceError(409, f"A {status.value.lower().replace('_', ' ')} appointment cannot be rescheduled.")
        self._enforce_patient_cutoff(old, "rescheduled")
        doctor = self._doctor(data.doctor_id or old.doctor_id)
        if doctor.id == old.doctor_id and data.starts_at == old.starts_at:
            raise ServiceError(422, "The appointment is already at that time.")

        # The appointment being moved must not block its own new time (e.g. shifting by one slot).
        slot = self._require_slot(doctor, data.starts_at, exclude_id=old.id)

        old_id, old_start = old.id, old.starts_at
        old.status = AppointmentStatus.CANCELLED.value
        old.cancel_reason = "Rescheduled"
        try:
            self.db.flush()                      # free the old range first, in this same transaction
            new = Appointment(id=uuid.uuid4(), clinic_id=self.clinic_id, doctor_id=doctor.id,
                              patient_id=old.patient_id, starts_at=slot.starts_at, ends_at=slot.occupies_until,
                              status=AppointmentStatus.CONFIRMED.value, rescheduled_from=old_id)
            self.db.add(new)
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()                   # restores the original appointment untouched
            if _sqlstate(exc) == EXCLUSION_VIOLATION:
                raise ServiceError(409, "That time was just taken. Your original appointment is unchanged.") from None
            raise
        self._audit("appointment.rescheduled", new.id, from_appointment=str(old_id), by_role=self.role.value,
                    old_start=old_start.isoformat(), new_start=slot.starts_at.isoformat())
        owner = self.db.scalar(select(Patient.user_id).where(
            Patient.id == old.patient_id, Patient.clinic_id == self.clinic_id))
        self._emit(old, "rescheduled_away", owner)
        self._emit(new, "rescheduled", owner)
        self._flush("That time was just taken. Please choose another slot.")
        notify_appointment(self.db, self.tenant, new, "appointment.rescheduled", owner)
        self._commit("That time was just taken. Your original appointment is unchanged.")
        return self.get(new.id)

    def confirm(self, appointment_id: uuid.UUID) -> AppointmentOut:
        appt = self._locked(appointment_id)
        if appt.status != AppointmentStatus.PENDING:
            raise ServiceError(409, "Only pending appointments can be confirmed.")
        appt.status = AppointmentStatus.CONFIRMED.value
        self._audit("appointment.confirmed", appt.id, by_role=self.role.value)
        self._emit(appt, "confirmed")
        self._flush("That time conflicts with another booking.")
        notify_appointment(self.db, self.tenant, appt, "appointment.confirmed")
        self.db.commit()
        return self.get(appt.id)
