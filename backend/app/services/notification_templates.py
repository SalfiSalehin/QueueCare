"""Message text. Pure functions: easy to test, no database.

Messages deliberately carry the minimum: who/where/when. No diagnosis, no medical detail, no other
patient's identity. Times are shown in the clinic's own time zone.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TYPES = ("appointment.booked", "appointment.confirmed", "appointment.cancelled", "appointment.rescheduled",
         "appointment.reminder", "queue.called")


def _when(payload: dict[str, Any]) -> str:
    moment = datetime.fromisoformat(payload["starts_at"]).astimezone(ZoneInfo(payload.get("tz") or "UTC"))
    return moment.strftime("%a %d %b %Y, %H:%M")


def render(kind: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Return (title, body) for a notification type."""
    clinic, doctor = payload.get("clinic_name", "the clinic"), payload.get("doctor_name", "your doctor")
    if kind == "appointment.booked":
        return "Appointment booked", f"Your appointment with {doctor} at {clinic} is booked for {_when(payload)}."
    if kind == "appointment.confirmed":
        return "Appointment confirmed", f"Your appointment with {doctor} at {clinic} on {_when(payload)} is confirmed."
    if kind == "appointment.cancelled":
        return "Appointment cancelled", f"Your appointment with {doctor} at {clinic} on {_when(payload)} was cancelled."
    if kind == "appointment.rescheduled":
        return "Appointment rescheduled", f"Your appointment with {doctor} at {clinic} is now {_when(payload)}."
    if kind == "appointment.reminder":
        return "Appointment reminder", f"Reminder: your appointment with {doctor} at {clinic} is on {_when(payload)}."
    if kind == "queue.called":
        label = payload.get("token_label", "your token")
        return "It's your turn", f"{label} is being called. Please go to {doctor} at {clinic}."
    raise ValueError(f"unknown notification type: {kind}")
