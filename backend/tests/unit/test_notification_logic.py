"""Pure notification rules: channels, back-off, message text, mock providers. No database."""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.analytics_logic import ScheduleRule, ratio, scheduled_minutes
from app.services.notification_logic import backoff_seconds, channels_for
from app.services.notification_providers import MockEmailProvider, OutboundMessage, ProviderError
from app.services.notification_templates import TYPES, render


def user(**over):
    base = dict(is_active=True, email="a@example.com", email_verified=True, phone=None)
    base.update(over)
    return SimpleNamespace(**base)


# ------------------------------------------------------------------- channels
def test_in_app_always_email_only_when_verified():
    assert channels_for(user(), "appointment.booked") == ["IN_APP", "EMAIL"]
    assert channels_for(user(email_verified=False), "appointment.booked") == ["IN_APP"]
    assert channels_for(user(email=""), "appointment.booked") == ["IN_APP"]


def test_sms_only_for_time_critical_types_with_a_phone():
    phone = user(phone="+10000000000")
    assert "SMS" in channels_for(phone, "queue.called")
    assert "SMS" in channels_for(phone, "appointment.reminder")
    assert "SMS" not in channels_for(phone, "appointment.booked")
    assert "SMS" not in channels_for(user(), "queue.called")


def test_inactive_users_get_nothing_beyond_in_app():
    assert channels_for(user(is_active=False, phone="+10000000000"), "queue.called") == ["IN_APP"]


# -------------------------------------------------------------------- back-off
def test_backoff_doubles_and_is_capped():
    assert [backoff_seconds(n, 30) for n in (1, 2, 3, 4)] == [30, 60, 120, 240]
    assert backoff_seconds(30, 30) == 3600
    assert backoff_seconds(0, 30) == 30


# ------------------------------------------------------------------- templates
PAYLOAD = {"clinic_name": "Clinic Alpha", "doctor_name": "Dr Bookable", "tz": "Asia/Dhaka",
           "starts_at": "2026-11-20T08:30:00+00:00", "token_label": "G-007"}


@pytest.mark.parametrize("kind", [t for t in TYPES if t != "queue.called"])
def test_appointment_messages_show_the_time_in_the_clinic_timezone(kind):
    title, body = render(kind, PAYLOAD)
    assert title and "Dr Bookable" in body and "Clinic Alpha" in body
    assert "14:30" in body and "20 Nov 2026" in body            # 08:30 UTC is 14:30 in Dhaka (UTC+6)


def test_called_message_names_the_token_not_the_patient():
    title, body = render("queue.called", PAYLOAD)
    assert "G-007" in body and "Dr Bookable" in body and title == "It's your turn"


def test_unknown_type_is_rejected():
    with pytest.raises(ValueError):
        render("appointment.exploded", PAYLOAD)


# ------------------------------------------------------------- mock providers
def msg(key="k1") -> OutboundMessage:
    return OutboundMessage("EMAIL", "a@example.com", "s", "b", "appointment.booked", key)


def test_mock_provider_records_and_can_be_made_to_fail():
    provider = MockEmailProvider()
    provider.send(msg("a"))
    assert [m.idempotency_key for m in provider.outbox] == ["a"]
    provider.failure = lambda m: ProviderError("down")
    with pytest.raises(ProviderError):
        provider.send(msg("b"))
    assert len(provider.outbox) == 1
    provider.reset()
    assert not provider.outbox and provider.failure is None


# ------------------------------------------------------------ analytics logic
UTC_TZ = ZoneInfo("UTC")
NINE_TO_TWELVE = [ScheduleRule(d, time(9), time(12)) for d in range(7)]


def test_scheduled_minutes_counts_each_working_day():
    assert scheduled_minutes(NINE_TO_TWELVE, [], date(2026, 11, 2), date(2026, 11, 8), UTC_TZ) == 7 * 180
    only_mon = [ScheduleRule(0, time(9), time(12))]
    assert scheduled_minutes(only_mon, [], date(2026, 11, 2), date(2026, 11, 8), UTC_TZ) == 180   # one Monday


def test_valid_from_and_to_limit_a_rule():
    rule = [ScheduleRule(d, time(9), time(10), valid_from=date(2026, 11, 4), valid_to=date(2026, 11, 5))
            for d in range(7)]
    assert scheduled_minutes(rule, [], date(2026, 11, 2), date(2026, 11, 8), UTC_TZ) == 120


def test_time_off_is_subtracted_and_overlaps_are_not_double_counted():
    off = [(datetime(2026, 11, 3, 10, 0, tzinfo=UTC), datetime(2026, 11, 3, 11, 0, tzinfo=UTC)),
           (datetime(2026, 11, 3, 10, 30, tzinfo=UTC), datetime(2026, 11, 3, 11, 30, tzinfo=UTC))]
    total = scheduled_minutes(NINE_TO_TWELVE, off, date(2026, 11, 3), date(2026, 11, 3), UTC_TZ)
    assert total == 180 - 90                                       # 10:00-11:30 is off, counted once
    whole_day = [(datetime(2026, 11, 3, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC))]
    assert scheduled_minutes(NINE_TO_TWELVE, whole_day, date(2026, 11, 3), date(2026, 11, 3), UTC_TZ) == 0


def test_overlapping_rules_on_one_day_are_merged():
    rules = [ScheduleRule(1, time(9), time(12)), ScheduleRule(1, time(11), time(13))]
    assert scheduled_minutes(rules, [], date(2026, 11, 3), date(2026, 11, 3), UTC_TZ) == 240   # a Tuesday


def test_clinic_local_time_is_used_for_working_hours():
    dhaka = ZoneInfo("Asia/Dhaka")
    off = [(datetime(2026, 11, 3, 3, 0, tzinfo=UTC), datetime(2026, 11, 3, 4, 0, tzinfo=UTC))]   # 09:00-10:00 local
    assert scheduled_minutes([ScheduleRule(1, time(9), time(12))], off, date(2026, 11, 3), date(2026, 11, 3), dhaka) == 120


def test_ratio_is_none_without_a_denominator():
    assert ratio(1, 0) is None and ratio(0, 0) is None
    assert ratio(1, 4) == 0.25
