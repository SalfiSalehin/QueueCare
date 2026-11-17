"""Slot-length suggestions per doctor from completed consultations (read-only advice for admins)."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.errors import ServiceError
from app.schemas.analytics import SchedulingSuggestionsOut, SlotSuggestion
from app.services.scheduling_logic import MIN_SAMPLES, suggest

MAX_WINDOW_DAYS = 365

ADVICE = {
    "insufficient_data": f"Fewer than {MIN_SAMPLES} completed consultations in the window: no suggestion yet.",
    "keep": "The current slot length fits recent consultations. No change suggested.",
    "lengthen": "Many consultations run past the current slot, which pushes later patients back. "
                "A longer slot would fit most of them (fewer bookable slots per day).",
    "shorten": "The current slot is much longer than most consultations need. A shorter slot would free "
               "capacity (more bookable slots per day) but more consultations would overrun it.",
}


class SchedulingService:
    def __init__(self, db: Session, tenant: TenantContext, now: datetime | None = None) -> None:
        self.db = db
        self.cid = tenant.clinic.id
        self._now = now

    def suggestions(self, days: int) -> SchedulingSuggestionsOut:
        if not 7 <= days <= MAX_WINDOW_DAYS:
            raise ServiceError(422, f"days must be between 7 and {MAX_WINDOW_DAYS}.")
        since = (self._now or datetime.now(UTC)) - timedelta(days=days)
        doctors = list(self.db.execute(text(
            "SELECT id, display_name, default_slot_minutes FROM doctors "
            "WHERE clinic_id = :cid AND is_active ORDER BY display_name"), {"cid": self.cid}))
        durations: dict[object, list[float]] = defaultdict(list)
        for r in self.db.execute(text(
                "SELECT doctor_id, duration_minutes FROM consultations "
                "WHERE clinic_id = :cid AND duration_minutes IS NOT NULL AND started_at >= :since"),
                {"cid": self.cid, "since": since}):
            durations[r.doctor_id].append(float(r.duration_minutes))
        items = []
        for d in doctors:
            s = suggest(durations.get(d.id, []), int(d.default_slot_minutes))
            items.append(SlotSuggestion(
                doctor_id=d.id, display_name=d.display_name, status=s.status, consultations=s.n,
                current_slot_minutes=s.current_slot_minutes, suggested_slot_minutes=s.suggested_slot_minutes,
                median_minutes=s.median_minutes, p80_minutes=s.p80_minutes, overrun_share_now=s.overrun_share_now,
                overrun_share_suggested=s.overrun_share_suggested, advice=ADVICE[s.status]))
        return SchedulingSuggestionsOut(
            window_days=days, items=items,
            note="Suggestions come from simple statistics on completed consultations (the shortest 5-minute slot "
                 "that fits 80% of them). They are advice only: nothing is changed automatically.")
