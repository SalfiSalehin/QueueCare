"""Builds the real-time events for appointment changes (queue events are built in QueueService,
which already has the ordering context). All writes go into the caller's transaction."""
from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.services.outbox import emit
from app.websocket.channels import doctor_channel, staff_channel, user_channel


def appointment_changed(db: Session, *, clinic_id: uuid.UUID, appointment: Any,
                        patient_user_id: uuid.UUID | None, change: str) -> None:
    """Tell staff, the doctor, and the patient (if they have an account) that an appointment changed.
    The payload is identical for all three and contains no names."""
    data = {
        "appointment_id": str(appointment.id),
        "doctor_id": str(appointment.doctor_id),
        "status": appointment.status,
        "starts_at": appointment.starts_at.astimezone(UTC).isoformat(),
        "change": change,
    }
    channels = [staff_channel(clinic_id), doctor_channel(clinic_id, appointment.doctor_id)]
    if patient_user_id is not None:
        channels.append(user_channel(clinic_id, patient_user_id))
    for channel in channels:
        emit(db, clinic_id=clinic_id, channel=channel, event_type="appointment.updated", payload=data)
