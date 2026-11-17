"""Pure queue rules: transitions, permissions, ordering, positions. No database."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.permissions.roles import ClinicRole, QueueStatus
from app.services.queue_logic import (
    ALLOWED_ROLES, TERMINAL, TRANSITIONS, Entry, QueueAction, format_token, next_status, order_waiting,
    people_ahead, role_may,
)

T0 = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)


def e(n, source="WALK_IN", priority=0, arrived=0, appt=None):
    return Entry(token_id=n, sequence_no=n, source=source, priority=priority,
                 arrived_at=T0 + timedelta(minutes=arrived),
                 appointment_starts_at=None if appt is None else T0 + timedelta(minutes=appt))


def test_happy_path_transitions():
    s = QueueStatus.WAITING
    for action, expected in [(QueueAction.CALL, "CALLED"), (QueueAction.START, "IN_CONSULTATION"),
                             (QueueAction.COMPLETE, "COMPLETED")]:
        s = next_status(s, action)
        assert s == expected


def test_terminal_states_allow_nothing():
    for status in TERMINAL:
        for action in QueueAction:
            assert next_status(status, action) is None


@pytest.mark.parametrize("status,action", [
    (QueueStatus.WAITING, QueueAction.START),       # must be called first
    (QueueStatus.WAITING, QueueAction.COMPLETE),
    (QueueStatus.CALLED, QueueAction.COMPLETE),
    (QueueStatus.IN_CONSULTATION, QueueAction.CANCEL),
    (QueueStatus.IN_CONSULTATION, QueueAction.SKIP),
    (QueueStatus.CALLED, QueueAction.CANCEL),
    (QueueStatus.SKIPPED, QueueAction.CALL),         # must be re-queued first
    (QueueStatus.WAITING, QueueAction.NO_SHOW),
])
def test_illegal_transitions_rejected(status, action):
    assert next_status(status, action) is None


def test_skipped_can_return_or_leave():
    assert next_status(QueueStatus.SKIPPED, QueueAction.REQUEUE) == "WAITING"
    assert next_status(QueueStatus.SKIPPED, QueueAction.NO_SHOW) == "NO_SHOW"
    assert next_status(QueueStatus.SKIPPED, QueueAction.CANCEL) == "CANCELLED"


def test_every_action_has_a_transition_and_roles():
    assert set(TRANSITIONS) == set(QueueAction) == set(ALLOWED_ROLES)


def test_role_permissions():
    assert role_may(ClinicRole.DOCTOR, QueueAction.CALL) and role_may(ClinicRole.RECEPTIONIST, QueueAction.START)
    assert not role_may(ClinicRole.PATIENT, QueueAction.CALL)
    assert role_may(ClinicRole.PATIENT, QueueAction.CANCEL)
    assert not role_may(ClinicRole.DOCTOR, QueueAction.CANCEL)       # doctors skip or no-show, they do not cancel
    for a in QueueAction:
        assert not role_may(ClinicRole.PATIENT, a) or a == QueueAction.CANCEL


def test_format_token():
    assert format_token("G", 7) == "G-007" and format_token("CD", 1234) == "CD-1234"


def test_fifo_orders_by_arrival_regardless_of_booking():
    items = [e(1, arrived=10), e(2, source="APPOINTMENT", arrived=20, appt=0), e(3, arrived=5)]
    assert [x.token_id for x in order_waiting(items, "FIFO")] == [3, 1, 2]


def test_appointment_first_puts_booked_before_walkins_by_appointment_time():
    items = [e(1, arrived=1), e(2, source="APPOINTMENT", arrived=30, appt=30),
             e(3, source="APPOINTMENT", arrived=40, appt=15), e(4, arrived=2)]
    assert [x.token_id for x in order_waiting(items, "APPOINTMENT_FIRST")] == [3, 2, 1, 4]


def test_priority_outranks_everything_then_ties_break_by_sequence():
    items = [e(1, source="APPOINTMENT", appt=0), e(2, priority=2, arrived=60), e(3, priority=1, arrived=1)]
    assert [x.token_id for x in order_waiting(items, "APPOINTMENT_FIRST")] == [2, 3, 1]
    same = [e(9, arrived=5), e(8, arrived=5)]
    assert [x.token_id for x in order_waiting(same, "FIFO")] == [8, 9]


def test_people_ahead_counts_serving_and_returns_none_if_not_waiting():
    ordered = order_waiting([e(1, arrived=1), e(2, arrived=2), e(3, arrived=3)], "FIFO")
    assert people_ahead(ordered, 1, serving=0) == 0
    assert people_ahead(ordered, 3, serving=1) == 3
    assert people_ahead(ordered, 99, serving=0) is None
