"""Pure queue rules: allowed status transitions, who may do what, ordering policy, positions.

No database or framework imports, so every rule here is unit-tested in isolation.

Ordering policy (clinic setting `queue_policy`)
- FIFO: highest priority first, then arrival time.
- APPOINTMENT_FIRST (default): highest priority first, then booked patients in order of their
  appointment time, then walk-ins in order of arrival.
  Trade-off: a steady stream of booked patients can keep a walk-in waiting. Staff can raise a
  walk-in's priority (when `walkin_priority_enabled`), and Phase 9 evaluates smarter policies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.permissions.roles import ClinicRole, QueueStatus

S = QueueStatus


class QueueAction(StrEnum):
    CALL = "call"
    START = "start"
    COMPLETE = "complete"
    SKIP = "skip"
    REQUEUE = "requeue"
    NO_SHOW = "no-show"
    CANCEL = "cancel"


# action -> (statuses it may start from, resulting status)
TRANSITIONS: dict[QueueAction, tuple[frozenset[QueueStatus], QueueStatus]] = {
    QueueAction.CALL: (frozenset({S.WAITING}), S.CALLED),
    QueueAction.START: (frozenset({S.CALLED}), S.IN_CONSULTATION),
    QueueAction.COMPLETE: (frozenset({S.IN_CONSULTATION}), S.COMPLETED),
    QueueAction.SKIP: (frozenset({S.WAITING, S.CALLED}), S.SKIPPED),
    QueueAction.REQUEUE: (frozenset({S.SKIPPED}), S.WAITING),
    QueueAction.NO_SHOW: (frozenset({S.CALLED, S.SKIPPED}), S.NO_SHOW),
    QueueAction.CANCEL: (frozenset({S.WAITING, S.SKIPPED}), S.CANCELLED),
}

TERMINAL = frozenset({S.COMPLETED, S.CANCELLED, S.NO_SHOW})

CLINICAL = {QueueAction.CALL, QueueAction.START, QueueAction.COMPLETE, QueueAction.SKIP,
            QueueAction.REQUEUE, QueueAction.NO_SHOW}

# Who may perform which action. DOCTOR is further limited to their own queue by the service;
# PATIENT may only leave the queue (cancel) from their own waiting token.
ALLOWED_ROLES: dict[QueueAction, frozenset[ClinicRole]] = {
    **{a: frozenset({ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST, ClinicRole.DOCTOR}) for a in CLINICAL},
    QueueAction.CANCEL: frozenset({ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST, ClinicRole.PATIENT}),
}


def next_status(current: QueueStatus, action: QueueAction) -> QueueStatus | None:
    """The status after `action`, or None if the action is not allowed from `current`."""
    sources, target = TRANSITIONS[action]
    return target if current in sources else None


def role_may(role: ClinicRole, action: QueueAction) -> bool:
    return role in ALLOWED_ROLES[action]


def format_token(prefix: str, sequence_no: int) -> str:
    return f"{prefix}-{sequence_no:03d}"


@dataclass(frozen=True)
class Entry:
    """What ordering needs to know about one waiting token."""

    token_id: object
    sequence_no: int
    source: str                    # WALK_IN | APPOINTMENT
    priority: int
    arrived_at: datetime
    appointment_starts_at: datetime | None = None


def sort_key(entry: Entry, policy: str) -> tuple:
    if policy == "FIFO" or entry.source != "APPOINTMENT" or entry.appointment_starts_at is None:
        booked_rank, when = (0, entry.arrived_at) if policy == "FIFO" else (1, entry.arrived_at)
    else:
        booked_rank, when = 0, entry.appointment_starts_at
    return (-entry.priority, booked_rank, when, entry.sequence_no)


def order_waiting(entries: list[Entry], policy: str) -> list[Entry]:
    return sorted(entries, key=lambda e: sort_key(e, policy))


def people_ahead(ordered: list[Entry], token_id: object, serving: int) -> int | None:
    """Patients who will be seen before `token_id`: those ahead in the waiting order plus anyone
    currently called or in consultation (`serving`). None if the token is not waiting."""
    for i, e in enumerate(ordered):
        if e.token_id == token_id:
            return i + serving
    return None
