"""Channel names and who may listen to what.

The SERVER decides every connection's channels from its verified membership. Clients never send
a channel name, so there is no client-controlled channel-authorization surface to get wrong.

Every channel starts with `clinic:{clinic_id}:`, so a message for one clinic can never match a
connection that belongs to another.

  clinic:{cid}:staff          clinic admins and receptionists: clinic-wide queue/appointment changes
  clinic:{cid}:doctor:{did}   the doctor profile `did` (their own queue and appointments)
  clinic:{cid}:user:{uid}     one user: their own token position / appointment status
"""
from __future__ import annotations

import uuid

from app.permissions.roles import ClinicRole


def staff_channel(clinic_id: uuid.UUID | str) -> str:
    return f"clinic:{clinic_id}:staff"


def doctor_channel(clinic_id: uuid.UUID | str, doctor_id: uuid.UUID | str) -> str:
    return f"clinic:{clinic_id}:doctor:{doctor_id}"


def user_channel(clinic_id: uuid.UUID | str, user_id: uuid.UUID | str) -> str:
    return f"clinic:{clinic_id}:user:{user_id}"


def channels_for(
    role: ClinicRole, *, clinic_id: uuid.UUID, user_id: uuid.UUID, doctor_id: uuid.UUID | None = None
) -> frozenset[str]:
    """The only channels a connection with this role may receive."""
    channels = {user_channel(clinic_id, user_id)}
    if role in (ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST):
        channels.add(staff_channel(clinic_id))
    elif role == ClinicRole.DOCTOR and doctor_id is not None:
        channels.add(doctor_channel(clinic_id, doctor_id))
    return frozenset(channels)


def belongs_to_clinic(channel: str, clinic_id: uuid.UUID | str) -> bool:
    return channel.startswith(f"clinic:{clinic_id}:")
