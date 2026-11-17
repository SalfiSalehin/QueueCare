"""Role definitions. Role names must match the CHECK constraints in the schema."""
from __future__ import annotations

from enum import StrEnum


class PlatformRole(StrEnum):
    NONE = "NONE"
    SUPER_ADMIN = "SUPER_ADMIN"


class ClinicRole(StrEnum):
    CLINIC_ADMIN = "CLINIC_ADMIN"
    RECEPTIONIST = "RECEPTIONIST"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"


class ClinicStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DoctorStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    DELAYED = "DELAYED"
    OFF_DUTY = "OFF_DUTY"


class AppointmentStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# Statuses that occupy a doctor's time. MUST match the WHERE clause of the
# appointments_no_doctor_overlap exclusion constraint in migration 0001.
ACTIVE_APPOINTMENT_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_PROGRESS,
)

STAFF_ROLES = (ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST, ClinicRole.DOCTOR)


class QueueStatus(StrEnum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    IN_CONSULTATION = "IN_CONSULTATION"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# MUST match the WHERE clauses of the partial unique indexes in migration 0003.
LIVE_TOKEN_STATUSES = (QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_CONSULTATION, QueueStatus.SKIPPED)
ACTIVE_TOKEN_STATUSES = (QueueStatus.CALLED, QueueStatus.IN_CONSULTATION)
