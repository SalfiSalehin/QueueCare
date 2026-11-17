"""Response schema for WebSocket tickets."""
from __future__ import annotations

from pydantic import BaseModel


class TicketOut(BaseModel):
    ticket: str
    expires_in: int
    websocket_path: str = "/api/v1/ws"
