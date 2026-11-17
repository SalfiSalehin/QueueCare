"""Delivery providers for notifications (EMAIL and SMS). Only mocks exist: no message ever leaves the system.

A real provider would implement `send` and read its credentials from server-side secrets. It receives the
notification's idempotency key so that a provider supporting idempotent sends can drop a duplicate caused
by a crash between "sent" and "marked sent" (delivery is at-least-once, see docs/notifications.md).

Recipients and message bodies are never logged.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

log = logging.getLogger("queuecare.notifications")


@dataclass(frozen=True)
class OutboundMessage:
    channel: str            # "EMAIL" | "SMS"
    to: str
    subject: str
    body: str
    kind: str               # notification type, e.g. "appointment.booked"
    idempotency_key: str


class ProviderError(Exception):
    """Delivery failed. `permanent=True` means retrying cannot help (e.g. an invalid address)."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class NotificationProvider(Protocol):
    def send(self, message: OutboundMessage) -> None: ...


class MockProvider:
    """Records messages in memory (bounded). Tests can make it fail, to exercise retries."""

    def __init__(self) -> None:
        self.outbox: deque[OutboundMessage] = deque(maxlen=1000)
        self.failure: Callable[[OutboundMessage], Exception | None] | None = None
        self._lock = threading.Lock()

    def send(self, message: OutboundMessage) -> None:
        if self.failure is not None:
            error = self.failure(message)
            if error is not None:
                raise error
        with self._lock:
            self.outbox.append(message)
        log.info("mock %s sent kind=%s", message.channel.lower(), message.kind)

    def reset(self) -> None:
        with self._lock:
            self.outbox.clear()
        self.failure = None


class MockEmailProvider(MockProvider):
    pass


class MockSMSProvider(MockProvider):
    pass


@lru_cache
def get_providers() -> dict[str, NotificationProvider]:
    return {"EMAIL": MockEmailProvider(), "SMS": MockSMSProvider()}
