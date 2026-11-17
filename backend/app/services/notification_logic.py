"""Pure notification rules (no database, no framework): which channels, and how long to wait before a retry."""
from __future__ import annotations

from typing import Any

# SMS only for time-critical types: there is no phone verification or consent record yet.
SMS_TYPES = frozenset({"appointment.reminder", "queue.called"})
MAX_BACKOFF_SECONDS = 3600


def channels_for(user: Any, kind: str) -> list[str]:
    """IN_APP always; EMAIL only to a verified address; SMS only for time-critical types with a phone."""
    channels = ["IN_APP"]
    if user.is_active and user.email_verified and user.email:
        channels.append("EMAIL")
    if user.is_active and user.phone and kind in SMS_TYPES:
        channels.append("SMS")
    return channels


def backoff_seconds(attempt: int, base: int) -> int:
    """Delay before retry number `attempt` (1 = after the first failure): base * 2^(attempt-1), capped."""
    return min(base * 2 ** max(0, attempt - 1), MAX_BACKOFF_SECONDS)
