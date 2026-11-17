"""Pure unit tests for the slot engine (no database)."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.slots import Window, compute_slots, day_bounds_utc, local_to_utc

UTC_TZ = ZoneInfo("UTC")
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
MON = date(2030, 1, 7)   # a Monday


def slots(windows, *, tz=UTC_TZ, d0=MON, d1=None, slot=15, buffer=5, busy=(), earliest=LONG_AGO, latest=FAR_FUTURE):
    return compute_slots(windows=windows, tz=tz, from_date=d0, to_date=d1 or d0, slot_minutes=slot,
                         buffer_minutes=buffer, busy=list(busy), earliest=earliest, latest=latest)


def hm(s):
    return s.starts_at.strftime("%H:%M")


def test_grid_uses_consultation_plus_buffer_and_occupancy_must_fit_the_window():
    out = slots([Window(0, time(9), time(12))])
    assert [hm(s) for s in out] == ["09:00", "09:20", "09:40", "10:00", "10:20", "10:40", "11:00", "11:20", "11:40"]
    assert out[0].ends_at - out[0].starts_at == timedelta(minutes=15)           # consultation only
    assert out[0].occupies_until - out[0].starts_at == timedelta(minutes=20)    # includes buffer
    assert out[-1].occupies_until == datetime(2030, 1, 7, 12, 0, tzinfo=UTC)    # never beyond the window


def test_remainder_that_cannot_fit_a_full_slot_is_dropped():
    out = slots([Window(0, time(9), time(9, 50))])        # 50 min -> two 20-min steps, 10 min left over
    assert [hm(s) for s in out] == ["09:00", "09:20"]


def test_zero_buffer_packs_slots_back_to_back():
    out = slots([Window(0, time(9), time(10))], slot=20, buffer=0)
    assert [hm(s) for s in out] == ["09:00", "09:20", "09:40"]


def test_only_matching_weekday_and_validity_dates_apply():
    w = [Window(0, time(9), time(10), valid_from=date(2030, 1, 14), valid_to=date(2030, 1, 20))]
    assert slots(w, d0=MON) == []                                       # before valid_from
    assert slots(w, d0=date(2030, 1, 14)) != []                         # valid_from is inclusive
    assert slots(w, d0=date(2030, 1, 21)) == []                         # after valid_to
    assert slots(w, d0=date(2030, 1, 15)) == []                         # a Tuesday


def test_multiple_windows_and_date_range_are_sorted():
    w = [Window(0, time(14), time(15)), Window(0, time(9), time(10)), Window(1, time(9), time(10))]
    out = slots(w, d0=MON, d1=date(2030, 1, 8))
    starts = [s.starts_at for s in out]
    assert starts == sorted(starts)
    assert {s.starts_at.date() for s in out} == {date(2030, 1, 7), date(2030, 1, 8)}


def test_busy_intervals_remove_every_overlapping_slot_but_not_touching_ones():
    busy = [(datetime(2030, 1, 7, 10, 0, tzinfo=UTC), datetime(2030, 1, 7, 10, 30, tzinfo=UTC))]
    out = slots([Window(0, time(9), time(12))], busy=busy)
    got = [hm(s) for s in out]
    assert "10:00" not in got and "10:20" not in got                    # overlap the busy block
    assert "09:40" in got and "10:40" in got                            # 09:40 occupies until 10:00 exactly: touching is fine
    assert len(out) == 7


def test_buffer_is_part_of_occupancy_for_conflicts():
    # An existing booking occupying 09:20-09:40 blocks 09:20 only; neighbours stay free.
    busy = [(datetime(2030, 1, 7, 9, 20, tzinfo=UTC), datetime(2030, 1, 7, 9, 40, tzinfo=UTC))]
    got = [hm(s) for s in slots([Window(0, time(9), time(10))], busy=busy)]
    assert got == ["09:00", "09:40"]


def test_minimum_notice_and_booking_horizon():
    w = [Window(0, time(9), time(12))]
    earliest = datetime(2030, 1, 7, 10, 0, tzinfo=UTC)
    latest = datetime(2030, 1, 7, 11, 0, tzinfo=UTC)
    got = [hm(s) for s in slots(w, earliest=earliest, latest=latest)]
    assert got == ["10:00", "10:20", "10:40"]            # earliest inclusive, latest exclusive


def test_clinic_timezone_shifts_utc_instants():
    out = slots([Window(0, time(9), time(10))], tz=ZoneInfo("Asia/Dhaka"))      # UTC+6, no DST
    assert out[0].starts_at == datetime(2030, 1, 7, 3, 0, tzinfo=UTC)


def test_spring_forward_day_has_fewer_real_hours():
    tz = ZoneInfo("America/New_York")
    d = date(2030, 3, 10)                                 # clocks jump 02:00 -> 03:00; a Sunday
    out = slots([Window(6, time(1), time(4))], tz=tz, d0=d, slot=20, buffer=0)
    assert len(out) == 6                                  # only 2 real hours, not 3
    assert out[0].starts_at == datetime(2030, 3, 10, 6, 0, tzinfo=UTC)          # 01:00 EST
    assert out[-1].occupies_until == datetime(2030, 3, 10, 8, 0, tzinfo=UTC)    # 04:00 EDT


def test_fall_back_day_has_extra_real_hour():
    tz = ZoneInfo("America/New_York")
    d = date(2030, 11, 3)                                 # clocks repeat 01:00-02:00; a Sunday
    out = slots([Window(6, time(1), time(4))], tz=tz, d0=d, slot=20, buffer=0)
    assert len(out) == 12                                 # 4 real hours


def test_day_bounds_follow_clinic_midnight():
    start, end = day_bounds_utc(MON, MON, ZoneInfo("Asia/Dhaka"))
    assert start == datetime(2030, 1, 6, 18, 0, tzinfo=UTC) and end - start == timedelta(hours=24)


def test_local_to_utc_ignores_stray_tzinfo_on_the_time():
    assert local_to_utc(MON, time(9, tzinfo=UTC), ZoneInfo("Asia/Dhaka")) == datetime(2030, 1, 7, 3, tzinfo=UTC)


def test_invalid_arguments_rejected():
    with pytest.raises(ValueError):
        slots([Window(0, time(9), time(10))], d0=MON, d1=MON - timedelta(days=1))
    with pytest.raises(ValueError):
        slots([Window(0, time(9), time(10))], slot=0)
    with pytest.raises(ValueError):
        slots([Window(0, time(9), time(10))], buffer=-1)
