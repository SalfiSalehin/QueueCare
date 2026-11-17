"""Email provider abstraction. Only a mock provider exists for now (Phase 8 expands this).

Real providers must read credentials from environment/secret storage on the server only.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str
    kind: str  # e.g. "password_reset", "email_verify"


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class MockEmailProvider:
    """Records messages in memory (bounded). In development it also logs the body so the
    reset/verify links can be used without a real mail server. Bodies are never logged
    in any other environment because they contain one-time tokens."""

    def __init__(self, log_bodies: bool = False) -> None:
        self.outbox: deque[EmailMessage] = deque(maxlen=200)
        self._log_bodies = log_bodies

    def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)
        if self._log_bodies:
            log.info("MOCK EMAIL to=%s kind=%s\n%s", message.to, message.kind, message.body)
        else:
            log.info("mock email queued kind=%s", message.kind)


@lru_cache
def get_email_provider() -> EmailProvider:
    return MockEmailProvider(log_bodies=get_settings().app_env == "development")
