from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    body: str
    read: bool
    created_at: datetime


class UnreadCount(BaseModel):
    count: int
