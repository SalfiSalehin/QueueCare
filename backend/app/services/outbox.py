"""Write real-time events into the transactional outbox.

`emit` only adds a row to the CALLER's transaction. If the business change rolls back, the event
disappears with it (no phantom notifications); if it commits, the event is guaranteed to be
delivered at least once by the relay (app/workers/outbox_relay.py).

Payloads are deliberately small "something changed" hints plus a few state fields. They never
carry other patients' names or any clinical data.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import OutboxEvent
from app.websocket.channels import belongs_to_clinic


def emit(db: Session, *, clinic_id: uuid.UUID, channel: str, event_type: str, payload: dict[str, Any]) -> None:
    if not belongs_to_clinic(channel, clinic_id):
        # Programming error guard: an event must never be published into another clinic's channel.
        raise ValueError("channel does not belong to the clinic")
    db.add(OutboxEvent(id=uuid.uuid4(), clinic_id=clinic_id, channel=channel, event_type=event_type,
                       payload=payload))


def envelope(row: OutboxEvent) -> str:
    """The exact text sent to WebSocket clients. `id` is stable across re-deliveries, so clients
    deduplicate on it (delivery is at-least-once)."""
    return json.dumps(
        {"type": "event", "id": str(row.id), "event": row.event_type, "version": row.version,
         "ts": row.created_at.isoformat(), "data": row.payload},
        separators=(",", ":"),
    )
