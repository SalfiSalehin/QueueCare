"""Live queue business logic: walk-ins, check-in, token allocation, state machine, doctor workflow.

Concurrency model
- Token numbers come from one atomic `INSERT ... ON CONFLICT DO UPDATE` on `queue_counters`; the
  row lock serializes allocation per clinic/day/prefix, and the counter shares the token's
  transaction, so there are no duplicates and no gaps.
- "One patient called/in consultation per doctor" and "one live token per patient per doctor per
  day" are partial unique indexes (migration 0003). Two doctors/clerks racing get one winner and
  one HTTP 409 from the database, not from a check-then-act in Python.
- Rows being changed are locked (FOR UPDATE) so two people cannot act on one token at once.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.errors import ServiceError
from app.models import (
    Appointment, Consultation, Department, Doctor, Patient, QueueCounter, QueueToken, QueueTokenEvent,
)
from app.permissions.roles import (
    ACTIVE_TOKEN_STATUSES, LIVE_TOKEN_STATUSES, AppointmentStatus, ClinicRole, DoctorStatus, QueueStatus,
)
from app.schemas.clinic import ClinicSettings
from app.schemas.queue import EstimateOut, FactorOut, MyTokenOut, QueueBoard, TokenEventOut, TokenOut, TransitionBody, WalkInCreate
from app.services.audit_service import record_audit
from app.services.notification_service import notify_token_called
from app.services.outbox import emit
from app.services.prediction_service import (
    HEURISTIC_NOTE, SYNTHETIC_NOTE, PredictionService, record_actual_wait,
)
from app.websocket.channels import doctor_channel, staff_channel, user_channel
from app.services.queue_logic import Entry, QueueAction, format_token, next_status, order_waiting, people_ahead, role_may


UNIQUE_VIOLATION = "23505"
FRONT_DESK = (ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST)
_ACTIVE = [s.value for s in ACTIVE_TOKEN_STATUSES]
_LIVE = [s.value for s in LIVE_TOKEN_STATUSES]
MAX_PATIENT_FANOUT = 200      # bound outbox rows per change; beyond this patients rely on REST polling
_PAST = {
    QueueAction.CALL: "called", QueueAction.START: "started", QueueAction.COMPLETE: "completed",
    QueueAction.SKIP: "skipped", QueueAction.REQUEUE: "put back in the queue",
    QueueAction.NO_SHOW: "marked as a no-show", QueueAction.CANCEL: "cancelled",
}

# Appointment status that mirrors each queue action (only for tokens that came from an appointment).
_APPT_SYNC = {
    QueueAction.START: AppointmentStatus.IN_PROGRESS,
    QueueAction.COMPLETE: AppointmentStatus.COMPLETED,
    QueueAction.NO_SHOW: AppointmentStatus.NO_SHOW,
    QueueAction.CANCEL: AppointmentStatus.CANCELLED,
}


def _violated(exc: IntegrityError) -> tuple[str | None, str | None]:
    orig = exc.orig
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    diag = getattr(orig, "diag", None)
    return code, getattr(diag, "constraint_name", None)


class QueueService:
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
    def today(self) -> date:
        return self._now().astimezone(self.tz).date()

    def _require(self, *roles: ClinicRole) -> None:
        if self.role not in roles:
            raise ServiceError(403, "You do not have permission to do that.")

    def _doctor(self, doctor_id: uuid.UUID) -> Doctor:
        doctor = self.db.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == self.clinic_id))
        if doctor is None or not doctor.is_active:
            raise ServiceError(404, "Doctor not found.")
        if self.role == ClinicRole.DOCTOR and doctor.user_id != self.actor_id:
            raise ServiceError(404, "Doctor not found.")          # a doctor only sees their own queue
        return doctor

    def _audit(self, action: str, entity_id: uuid.UUID, **meta: Any) -> None:
        record_audit(self.db, action=action, actor_user_id=self.actor_id, clinic_id=self.clinic_id,
                     entity_type="queue_token", entity_id=entity_id, ip=self.ip, metadata=meta)

    def _log(self, token: QueueToken, from_status: str | None, reason: str | None = None) -> None:
        self.db.add(QueueTokenEvent(id=uuid.uuid4(), clinic_id=self.clinic_id, token_id=token.id,
                                    actor_user_id=self.actor_id, from_status=from_status,
                                    to_status=token.status, reason=reason))

    def _emit(self, token: QueueToken, change: str) -> None:
        """Write the real-time events for this change into the current transaction (transactional outbox).

        Staff and the doctor get a small "queue changed" hint. Each patient WITH an account who is in
        this doctor's queue today gets only their own token's status and how many people are ahead.
        No patient ever receives another patient's identity."""
        cid = self.clinic_id
        base = {"doctor_id": str(token.doctor_id), "token_id": str(token.id), "token_label": token.token_label,
                "status": token.status, "token_version": token.version, "change": change}
        for channel in (staff_channel(cid), doctor_channel(cid, token.doctor_id)):
            emit(self.db, clinic_id=cid, channel=channel, event_type="queue.updated", payload=base)

        ordered = self._ordered_waiting(token.doctor_id, token.queue_date)
        position = {e.token_id: i for i, e in enumerate(ordered)}
        serving = self.db.scalar(select(func.count()).select_from(QueueToken).where(
            QueueToken.clinic_id == cid, QueueToken.doctor_id == token.doctor_id,
            QueueToken.status.in_(_ACTIVE))) or 0
        rows = self.db.execute(
            select(QueueToken.id, QueueToken.token_label, QueueToken.status, QueueToken.version, Patient.user_id)
            .join(Patient, and_(Patient.id == QueueToken.patient_id, Patient.clinic_id == QueueToken.clinic_id))
            .where(QueueToken.clinic_id == cid, QueueToken.doctor_id == token.doctor_id,
                   QueueToken.queue_date == token.queue_date, Patient.user_id.is_not(None),
                   or_(QueueToken.status.in_(_LIVE), QueueToken.id == token.id))
            .order_by(QueueToken.sequence_no).limit(MAX_PATIENT_FANOUT)
        ).all()
        for tid, label, status, version, patient_user_id in rows:
            ahead = position[tid] + serving if tid in position else None
            emit(self.db, clinic_id=cid, channel=user_channel(cid, patient_user_id), event_type="queue.position",
                 payload={"token_id": str(tid), "token_label": label, "doctor_id": str(token.doctor_id),
                          "status": status, "people_ahead": ahead, "token_version": version})

    def _conflict(self, exc: IntegrityError, mapping: dict[str, str]) -> ServiceError | None:
        """Map a database constraint violation to a friendly 409, or None if it is something else."""
        code, name = _violated(exc)
        if code == UNIQUE_VIOLATION and name in mapping:
            return ServiceError(409, mapping[name])
        return None

    def _next_sequence(self, prefix: str, day: date) -> int:
        stmt = (
            pg_insert(QueueCounter)
            .values(clinic_id=self.clinic_id, queue_date=day, prefix=prefix, last_sequence=1)
            .on_conflict_do_update(
                index_elements=[QueueCounter.clinic_id, QueueCounter.queue_date, QueueCounter.prefix],
                set_={"last_sequence": QueueCounter.last_sequence + 1, "updated_at": func.now()},
            )
            .returning(QueueCounter.last_sequence)
        )
        return int(self.db.execute(stmt).scalar_one())

    def _new_token(self, doctor: Doctor, patient_id: uuid.UUID, *, source: str,
                   appointment_id: uuid.UUID | None, priority: int) -> QueueToken:
        prefix = self.db.scalar(select(Department.queue_prefix).where(
            Department.id == doctor.department_id, Department.clinic_id == self.clinic_id))
        if prefix is None:
            raise ServiceError(409, "The doctor's department is not available.")
        now = self._now()
        day = now.astimezone(self.tz).date()
        seq = self._next_sequence(prefix, day)
        token = QueueToken(
            id=uuid.uuid4(), clinic_id=self.clinic_id, doctor_id=doctor.id, patient_id=patient_id,
            appointment_id=appointment_id, queue_date=day, prefix=prefix, sequence_no=seq,
            token_label=format_token(prefix, seq), source=source, status=QueueStatus.WAITING.value,
            priority=priority, arrived_at=now, version=1)
        self.db.add(token)
        self.db.flush()
        self._log(token, None, "Joined the queue")
        return token

    _CREATE_CONFLICTS = {
        "uq_queue_tokens_live_patient": "This patient is already in this doctor's queue today.",
        "uq_queue_tokens_appointment": "This appointment has already been checked in.",
    }

    # ----------------------------------------------------------------- joining
    def walk_in(self, data: WalkInCreate) -> TokenOut:
        self._require(*FRONT_DESK)
        doctor = self._doctor(data.doctor_id)
        if doctor.status == DoctorStatus.OFF_DUTY:
            raise ServiceError(409, "This doctor is off duty.")
        if data.priority > 0 and not self.settings.walkin_priority_enabled:
            raise ServiceError(422, "Priority walk-ins are not enabled for this clinic.")
        patient = self.db.scalar(select(Patient).where(
            Patient.id == data.patient_id, Patient.clinic_id == self.clinic_id, Patient.deleted_at.is_(None)))
        if patient is None:
            raise ServiceError(404, "Patient not found.")
        try:
            token = self._new_token(doctor, patient.id, source="WALK_IN", appointment_id=None,
                                    priority=data.priority)
            self._audit("queue.walk_in", token.id, label=token.token_label, priority=data.priority)
            self._emit(token, "walk_in")
            self._log_prediction(token, doctor, None)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            friendly = self._conflict(exc, self._CREATE_CONFLICTS)
            if friendly:
                raise friendly from None
            raise
        return self.get_token(token.id)

    def check_in(self, appointment_id: uuid.UUID) -> TokenOut:
        self._require(*FRONT_DESK)
        appt = self.db.scalar(select(Appointment).where(
            Appointment.id == appointment_id, Appointment.clinic_id == self.clinic_id).with_for_update())
        if appt is None:
            raise ServiceError(404, "Appointment not found.")
        if appt.status == AppointmentStatus.PENDING:
            raise ServiceError(409, "Confirm the appointment before checking the patient in.")
        if appt.status == AppointmentStatus.CHECKED_IN:
            raise ServiceError(409, "This appointment has already been checked in.")
        if appt.status != AppointmentStatus.CONFIRMED:
            raise ServiceError(409, f"A {appt.status.lower().replace('_', ' ')} appointment cannot be checked in.")
        if appt.starts_at.astimezone(self.tz).date() != self.today():
            raise ServiceError(409, "Patients can only be checked in on the day of their appointment.")
        doctor = self._doctor(appt.doctor_id)
        if doctor.status == DoctorStatus.OFF_DUTY:
            raise ServiceError(409, "This doctor is off duty.")
        try:
            token = self._new_token(doctor, appt.patient_id, source="APPOINTMENT",
                                    appointment_id=appt.id, priority=0)
            appt.status = AppointmentStatus.CHECKED_IN.value
            self._audit("queue.check_in", token.id, label=token.token_label, appointment_id=str(appt.id))
            self._emit(token, "check_in")
            self._log_prediction(token, doctor, appt.starts_at)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            friendly = self._conflict(exc, self._CREATE_CONFLICTS)
            if friendly:
                raise friendly from None
            raise
        return self.get_token(token.id)

    # -------------------------------------------------------------- predictions
    def _ahead_of(self, token: QueueToken) -> list[Entry] | None:
        ordered = self._ordered_waiting(token.doctor_id, token.queue_date)
        idx = next((i for i, e in enumerate(ordered) if e.token_id == token.id), None)
        return None if idx is None else ordered[:idx]

    def _log_prediction(self, token: QueueToken, doctor: Doctor, appt_start: datetime | None) -> None:
        """Best-effort: store what the model predicted when this patient joined. Never raises."""
        predictions = PredictionService(self.db, self.tenant, self._now)
        if not predictions.available:
            return
        ahead = self._ahead_of(token)
        if ahead is not None:
            predictions.log_arrival(token=token, doctor=doctor, appt_start=appt_start, ahead=ahead)

    def estimate(self, token_id: uuid.UUID) -> EstimateOut:
        """Estimated remaining wait for one token. Patients see only the median; staff and the doctor
        also see the range. Role scoping comes from `_rows` (a patient can only reach their own token)."""
        row = self.db.execute(self._rows([QueueToken.id == token_id])).first()
        if row is None:
            raise ServiceError(404, "Queue token not found.")
        token, _name, _doc, appt_start = row
        if token.status != QueueStatus.WAITING:
            return EstimateOut(token_id=token.id, status=token.status, source="not_waiting",
                               note="This token is not waiting, so there is no wait to estimate.")
        ahead = self._ahead_of(token)
        if ahead is None:
            raise ServiceError(404, "Queue token not found.")
        predictions = PredictionService(self.db, self.tenant, self._now)
        doctor = self.db.scalar(select(Doctor).where(Doctor.id == token.doctor_id,
                                                     Doctor.clinic_id == self.clinic_id))
        if doctor is None:
            raise ServiceError(404, "Queue token not found.")
        snap = predictions.snapshot(token=token, doctor=doctor, appt_start=appt_start, ahead=ahead,
                                    as_of=self._now())
        result = predictions.estimate(snap)
        show_range = self.role != ClinicRole.PATIENT and result.lower is not None
        factors: list[FactorOut] | None = None
        typical: float | None = None
        if show_range and result.source == "model":                  # staff only; patients never get this
            explanation = predictions.explain(result.features)
            if explanation is not None:
                factors = [FactorOut(feature=f.feature, label=f.label, minutes=f.minutes)
                           for f in explanation.top(3)]
                typical = round(max(0.0, explanation.base_minutes), 1)
        return EstimateOut(
            token_id=token.id, status=token.status, source=result.source, median_minutes=result.median,
            lower_minutes=result.lower if show_range else None,
            upper_minutes=result.upper if show_range else None, model_version=result.model_version,
            factors=factors, typical_minutes=typical,
            note=SYNTHETIC_NOTE if result.source == "model" else HEURISTIC_NOTE)

    # ----------------------------------------------------------------- reading
    def _rows(self, where: list[Any]) -> Select[Any]:
        stmt = (
            select(QueueToken, Patient.full_name, Doctor.display_name, Appointment.starts_at)
            .join(Patient, and_(Patient.id == QueueToken.patient_id, Patient.clinic_id == QueueToken.clinic_id))
            .join(Doctor, and_(Doctor.id == QueueToken.doctor_id, Doctor.clinic_id == QueueToken.clinic_id))
            .outerjoin(Appointment, and_(Appointment.id == QueueToken.appointment_id,
                                         Appointment.clinic_id == QueueToken.clinic_id))
            .where(QueueToken.clinic_id == self.clinic_id, *where)
        )
        if self.role == ClinicRole.PATIENT:
            stmt = stmt.where(Patient.user_id == self.actor_id)
        elif self.role == ClinicRole.DOCTOR:
            stmt = stmt.where(Doctor.user_id == self.actor_id)
        return stmt

    @staticmethod
    def _entry(token: QueueToken, appt_start: datetime | None) -> Entry:
        return Entry(token_id=token.id, sequence_no=token.sequence_no, source=token.source,
                     priority=token.priority, arrived_at=token.arrived_at, appointment_starts_at=appt_start)

    @staticmethod
    def _out(token: QueueToken, patient_name: str, position: int | None = None) -> TokenOut:
        return TokenOut(
            id=token.id, token_label=token.token_label, doctor_id=token.doctor_id, patient_id=token.patient_id,
            patient_name=patient_name, appointment_id=token.appointment_id, source=token.source,
            status=token.status, priority=token.priority, queue_date=token.queue_date,
            arrived_at=token.arrived_at, called_at=token.called_at, started_at=token.started_at,
            completed_at=token.completed_at, position=position, version=token.version)

    def get_token(self, token_id: uuid.UUID) -> TokenOut:
        self._require(*FRONT_DESK, ClinicRole.DOCTOR)
        row = self.db.execute(self._rows([QueueToken.id == token_id])).first()
        if row is None:
            raise ServiceError(404, "Queue token not found.")
        token, patient_name, _doc, appt_start = row
        position = None
        if token.status == QueueStatus.WAITING:
            ordered = self._ordered_waiting(token.doctor_id, token.queue_date)
            idx = next((i for i, e in enumerate(ordered) if e.token_id == token.id), None)
            position = None if idx is None else idx + 1
        return self._out(token, patient_name, position)

    def _ordered_waiting(self, doctor_id: uuid.UUID, day: date, lock: bool = False) -> list[Entry]:
        stmt = (
            select(QueueToken, Appointment.starts_at)
            .outerjoin(Appointment, and_(Appointment.id == QueueToken.appointment_id,
                                         Appointment.clinic_id == QueueToken.clinic_id))
            .where(QueueToken.clinic_id == self.clinic_id, QueueToken.doctor_id == doctor_id,
                   QueueToken.queue_date == day, QueueToken.status == QueueStatus.WAITING.value)
        )
        if lock:
            stmt = stmt.with_for_update(of=QueueToken)
        return order_waiting([self._entry(t, s) for t, s in self.db.execute(stmt)], self.settings.queue_policy)

    def board(self, doctor_id: uuid.UUID, on_date: date | None) -> QueueBoard:
        self._require(*FRONT_DESK, ClinicRole.DOCTOR)
        doctor = self._doctor(doctor_id)
        day = on_date or self.today()
        rows = self.db.execute(self._rows([
            QueueToken.doctor_id == doctor.id,
            (QueueToken.queue_date == day) | QueueToken.status.in_(_ACTIVE),
        ])).all()
        by_id = {t.id: (t, name, start) for t, name, _d, start in rows}
        waiting_entries = order_waiting(
            [self._entry(t, s) for t, _n, s in by_id.values()
             if t.status == QueueStatus.WAITING and t.queue_date == day], self.settings.queue_policy)
        waiting = [self._out(by_id[e.token_id][0], by_id[e.token_id][1], i + 1)
                   for i, e in enumerate(waiting_entries)]
        serving = sorted((self._out(t, n) for t, n, _s in by_id.values() if t.status in _ACTIVE),
                         key=lambda o: o.arrived_at)
        skipped = sorted((self._out(t, n) for t, n, _s in by_id.values()
                          if t.status == QueueStatus.SKIPPED and t.queue_date == day), key=lambda o: o.arrived_at)
        finished = sum(1 for t, _n, _s in by_id.values()
                       if t.status == QueueStatus.COMPLETED and t.queue_date == day)
        return QueueBoard(doctor_id=doctor.id, doctor_name=doctor.display_name, doctor_status=doctor.status,
                          queue_date=day, policy=self.settings.queue_policy, serving=serving,
                          waiting=waiting, skipped=skipped, finished_today=finished)

    def mine(self) -> list[MyTokenOut]:
        self._require(ClinicRole.PATIENT)
        day = self.today()
        rows = self.db.execute(self._rows([QueueToken.queue_date == day]).order_by(QueueToken.arrived_at)).all()
        out: list[MyTokenOut] = []
        for token, _name, doctor_name, _start in rows:
            ahead = None
            if token.status == QueueStatus.WAITING:
                serving = self.db.scalar(select(func.count()).select_from(QueueToken).where(
                    QueueToken.clinic_id == self.clinic_id, QueueToken.doctor_id == token.doctor_id,
                    QueueToken.status.in_(_ACTIVE))) or 0
                ahead = people_ahead(self._ordered_waiting(token.doctor_id, day), token.id, serving)
            out.append(MyTokenOut(id=token.id, token_label=token.token_label, doctor_id=token.doctor_id,
                                  doctor_name=doctor_name, status=token.status, source=token.source,
                                  queue_date=token.queue_date, people_ahead=ahead))
        return out

    def events(self, token_id: uuid.UUID) -> list[TokenEventOut]:
        self._require(*FRONT_DESK, ClinicRole.DOCTOR)
        if self.db.execute(self._rows([QueueToken.id == token_id])).first() is None:
            raise ServiceError(404, "Queue token not found.")
        rows = self.db.scalars(select(QueueTokenEvent).where(
            QueueTokenEvent.clinic_id == self.clinic_id, QueueTokenEvent.token_id == token_id)
            .order_by(QueueTokenEvent.created_at, QueueTokenEvent.id))
        return [TokenEventOut(from_status=e.from_status, to_status=e.to_status, reason=e.reason,
                              actor_user_id=e.actor_user_id, created_at=e.created_at) for e in rows]

    # ------------------------------------------------------------ transitions
    def act(self, token_id: uuid.UUID, action: QueueAction, body: TransitionBody | None = None) -> TokenOut:
        if not role_may(self.role, action):
            raise ServiceError(403, "You do not have permission to do that.")
        row = self.db.execute(self._rows([QueueToken.id == token_id]).with_for_update(of=QueueToken)).first()
        if row is None:
            raise ServiceError(404, "Queue token not found.")      # also: exists but is not yours
        token = row[0]
        self._apply(token, action, body.reason if body else None)
        return self.get_token(token.id) if self.role != ClinicRole.PATIENT else self._patient_view(token)

    def _patient_view(self, token: QueueToken) -> TokenOut:
        # A patient who just left the queue gets their own token back (their own name, no one else's).
        return self._out(token, self.tenant.user.full_name)

    def _apply(self, token: QueueToken, action: QueueAction, reason: str | None) -> None:
        current = QueueStatus(token.status)
        target = next_status(current, action)
        if target is None:
            raise ServiceError(409, f"A {current.value.lower().replace('_', ' ')} token cannot be {_PAST[action]}.")
        if self.role == ClinicRole.PATIENT and current != QueueStatus.WAITING:
            raise ServiceError(409, "You can only leave the queue while you are still waiting.")
        now = self._now()
        try:
            token.status = target.value
            token.version += 1
            if action == QueueAction.CALL:
                token.called_at = now
            elif action == QueueAction.START:
                token.started_at = now
                wait = max(0, int((now - token.arrived_at).total_seconds() // 60))
                self.db.add(Consultation(id=uuid.uuid4(), clinic_id=self.clinic_id, token_id=token.id,
                                         doctor_id=token.doctor_id, started_at=now, actual_wait_minutes=wait))
                record_actual_wait(self.db, self.clinic_id, token.id,
                                   max(0.0, (now - token.arrived_at).total_seconds() / 60.0))
            elif action == QueueAction.COMPLETE:
                token.completed_at = now
                consult = self.db.scalar(select(Consultation).where(
                    Consultation.token_id == token.id, Consultation.clinic_id == self.clinic_id))
                if consult is not None:
                    consult.ended_at = now
                    consult.duration_minutes = max(0, int((now - consult.started_at).total_seconds() // 60))
            elif action == QueueAction.REQUEUE:
                token.called_at = None
            if action in _APPT_SYNC and token.appointment_id is not None:
                appt = self.db.scalar(select(Appointment).where(
                    Appointment.id == token.appointment_id, Appointment.clinic_id == self.clinic_id))
                if appt is not None:
                    appt.status = _APPT_SYNC[action].value
                    if action == QueueAction.CANCEL:
                        appt.cancel_reason = reason or "Left the queue"
            self.db.flush()                      # surfaces the "one active per doctor" index violation here
            self._log(token, current.value, reason)
            self._audit(f"queue.{action.value.replace('-', '_')}", token.id, label=token.token_label,
                        from_status=current.value, to_status=target.value, by_role=self.role.value)
            self._emit(token, action.value.replace("-", "_"))
            if action == QueueAction.CALL:
                notify_token_called(self.db, self.tenant, token)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            friendly = self._conflict(exc, {
                "uq_queue_tokens_one_active_per_doctor":
                    "This doctor already has a patient called or in consultation. Finish or skip them first.",
                "uq_queue_tokens_live_patient": "This patient is already in this doctor's queue today.",
            })
            if friendly:
                raise friendly from None
            raise

    def call_next(self, doctor_id: uuid.UUID) -> TokenOut:
        """Call the patient who is next according to the clinic's ordering policy."""
        self._require(*FRONT_DESK, ClinicRole.DOCTOR)
        doctor = self._doctor(doctor_id)
        active = self.db.scalar(select(func.count()).select_from(QueueToken).where(
            QueueToken.clinic_id == self.clinic_id, QueueToken.doctor_id == doctor.id,
            QueueToken.status.in_(_ACTIVE))) or 0
        if active:
            raise ServiceError(409, "This doctor already has a patient called or in consultation.")
        ordered = self._ordered_waiting(doctor.id, self.today(), lock=True)
        if not ordered:
            raise ServiceError(409, "No patients are waiting.")
        row = self.db.execute(self._rows([QueueToken.id == ordered[0].token_id]).with_for_update(of=QueueToken)).first()
        if row is None:
            raise ServiceError(409, "No patients are waiting.")
        self._apply(row[0], QueueAction.CALL, "Called next")
        return self.get_token(row[0].id)
