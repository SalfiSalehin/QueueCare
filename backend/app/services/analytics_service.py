"""Clinic analytics: read-only aggregates, CLINIC_ADMIN only.

Every query filters on the clinic in context (and RLS enforces it independently), returns counts and
statistics only (no patient names or identifiers), and works on clinic-local dates: a range of
"2026-11-01 .. 2026-11-07" means local midnight to local midnight in the clinic's own time zone.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.errors import ServiceError
from app.schemas.analytics import (
    DateRange, DayPoint, DoctorUtilisation, DoctorUtilisationOut, HourLoad, LoadOut, OverviewOut,
    PredictionAccuracyOut, VersionAccuracy, WeekdayLoad, Distribution,
)
from app.services.analytics_logic import ScheduleRule, ratio, scheduled_minutes

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30
MIN_PREDICTIONS = 30


def _f(value: Any, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


class AnalyticsService:
    def __init__(self, db: Session, tenant: TenantContext, now: datetime | None = None) -> None:
        self.db = db
        self.cid = tenant.clinic.id
        self.tz_name = tenant.clinic.timezone
        self.tz = ZoneInfo(self.tz_name)
        self._now = now

    # ---------------------------------------------------------------- range
    def window(self, start: date | None, end: date | None) -> tuple[date, date, datetime, datetime]:
        today = (self._now or datetime.now(UTC)).astimezone(self.tz).date()
        end = end or today
        start = start or (end - timedelta(days=DEFAULT_RANGE_DAYS - 1))
        if end < start:
            raise ServiceError(422, "The end date must not be before the start date.")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ServiceError(422, f"The date range may cover at most {MAX_RANGE_DAYS} days.")
        lo = datetime.combine(start, time.min, tzinfo=self.tz).astimezone(UTC)
        hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=self.tz).astimezone(UTC)
        return start, end, lo, hi

    def _range(self, start: date, end: date) -> DateRange:
        return DateRange(start=start, end=end, timezone=self.tz_name)

    def _q(self, sql: str, **params: Any) -> list[Any]:
        return list(self.db.execute(text(sql), {"cid": self.cid, "tz": self.tz_name, **params}))

    @staticmethod
    def _dist(row: Any) -> Distribution:
        return Distribution(n=int(row.n or 0), mean=_f(row.mean), p50=_f(row.p50), p90=_f(row.p90), max=_f(row.max))

    # -------------------------------------------------------------- overview
    def overview(self, start_date: date | None, end_date: date | None) -> OverviewOut:
        start, end, lo, hi = self.window(start_date, end_date)
        appts = {r.status: int(r.n) for r in self._q(
            "SELECT status, count(*) AS n FROM appointments "
            "WHERE clinic_id = :cid AND starts_at >= :lo AND starts_at < :hi GROUP BY status", lo=lo, hi=hi)}
        tokens: dict[str, int] = defaultdict(int)
        walk_ins = 0
        for r in self._q(
                "SELECT status, source, count(*) AS n FROM queue_tokens "
                "WHERE clinic_id = :cid AND arrived_at >= :lo AND arrived_at < :hi GROUP BY status, source",
                lo=lo, hi=hi):
            tokens[r.status] += int(r.n)
            if r.source == "WALK_IN":
                walk_ins += int(r.n)
        tokens_total = sum(tokens.values())

        def dist(column: str) -> Distribution:
            row = self._q(
                f"SELECT count({column}) AS n, avg({column}) AS mean, "
                f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {column}) AS p50, "
                f"percentile_cont(0.9) WITHIN GROUP (ORDER BY {column}) AS p90, max({column}) AS max "
                "FROM consultations WHERE clinic_id = :cid AND started_at >= :lo AND started_at < :hi", lo=lo, hi=hi)[0]
            return self._dist(row)                                   # column names are constants below

        days: dict[date, dict[str, int]] = {}
        day = start
        while day <= end:
            days[day] = {"appointments": 0, "arrivals": 0, "consultations": 0}
            day += timedelta(days=1)
        for key, sql in (
                ("appointments", "SELECT (starts_at AT TIME ZONE :tz)::date AS d, count(*) AS n FROM appointments "
                                 "WHERE clinic_id = :cid AND starts_at >= :lo AND starts_at < :hi GROUP BY d"),
                ("arrivals", "SELECT (arrived_at AT TIME ZONE :tz)::date AS d, count(*) AS n FROM queue_tokens "
                             "WHERE clinic_id = :cid AND arrived_at >= :lo AND arrived_at < :hi GROUP BY d"),
                ("consultations", "SELECT (started_at AT TIME ZONE :tz)::date AS d, count(*) AS n FROM consultations "
                                  "WHERE clinic_id = :cid AND started_at >= :lo AND started_at < :hi GROUP BY d")):
            for r in self._q(sql, lo=lo, hi=hi):
                if r.d in days:
                    days[r.d][key] = int(r.n)

        completed, no_show = appts.get("COMPLETED", 0), appts.get("NO_SHOW", 0)
        return OverviewOut(
            range=self._range(start, end), appointments_total=sum(appts.values()), appointments_by_status=appts,
            no_show_rate=ratio(no_show, completed + no_show),
            cancellation_rate=ratio(appts.get("CANCELLED", 0), sum(appts.values())),
            tokens_total=tokens_total, tokens_by_status=dict(tokens), walk_in_share=ratio(walk_ins, tokens_total),
            wait_minutes=dist("actual_wait_minutes"), consultation_minutes=dist("duration_minutes"),
            daily=[DayPoint(date=d, **v) for d, v in days.items()])

    # --------------------------------------------------------------- doctors
    def doctors(self, start_date: date | None, end_date: date | None) -> DoctorUtilisationOut:
        start, end, lo, hi = self.window(start_date, end_date)
        doctors = self._q("SELECT id, display_name FROM doctors WHERE clinic_id = :cid AND is_active ORDER BY display_name")
        rules: dict[Any, list[ScheduleRule]] = defaultdict(list)
        for r in self._q("SELECT doctor_id, day_of_week, start_time, end_time, valid_from, valid_to "
                         "FROM doctor_schedules WHERE clinic_id = :cid"):
            rules[r.doctor_id].append(ScheduleRule(r.day_of_week, r.start_time, r.end_time, r.valid_from, r.valid_to))
        off: dict[Any, list[tuple[datetime, datetime]]] = defaultdict(list)
        for r in self._q("SELECT doctor_id, lower(period) AS s, upper(period) AS e FROM doctor_time_off "
                         "WHERE clinic_id = :cid AND period && tstzrange(:lo, :hi)", lo=lo, hi=hi):
            off[r.doctor_id].append((r.s or datetime.min.replace(tzinfo=UTC), r.e or datetime.max.replace(tzinfo=UTC)))
        booked = {r.doctor_id: float(r.m or 0) for r in self._q(
            "SELECT doctor_id, sum(extract(epoch FROM ends_at - starts_at)) / 60.0 AS m FROM appointments "
            "WHERE clinic_id = :cid AND status <> 'CANCELLED' AND starts_at >= :lo AND starts_at < :hi "
            "GROUP BY doctor_id", lo=lo, hi=hi)}
        seen = {r.doctor_id: r for r in self._q(
            "SELECT doctor_id, coalesce(sum(duration_minutes), 0) AS m, count(duration_minutes) AS n, "
            "avg(actual_wait_minutes) AS w FROM consultations "
            "WHERE clinic_id = :cid AND started_at >= :lo AND started_at < :hi GROUP BY doctor_id", lo=lo, hi=hi)}
        items = []
        for d in doctors:
            sched = scheduled_minutes(rules.get(d.id, []), off.get(d.id, []), start, end, self.tz)
            book = booked.get(d.id, 0.0)
            row = seen.get(d.id)
            busy = float(row.m) if row else 0.0
            items.append(DoctorUtilisation(
                doctor_id=d.id, display_name=d.display_name, scheduled_minutes=round(sched, 1),
                booked_minutes=round(book, 1), consultation_minutes=round(busy, 1),
                patients_seen=int(row.n) if row else 0, avg_wait_minutes=_f(row.w) if row else None,
                booked_utilisation=ratio(book, sched), busy_utilisation=ratio(busy, sched)))
        return DoctorUtilisationOut(range=self._range(start, end), items=items)

    # ------------------------------------------------------------------ load
    def load(self, start_date: date | None, end_date: date | None) -> LoadOut:
        start, end, lo, hi = self.window(start_date, end_date)
        hours = [HourLoad(hour=int(r.h), arrivals=int(r.n), avg_wait_minutes=_f(r.w)) for r in self._q(
            "SELECT extract(hour FROM t.arrived_at AT TIME ZONE :tz)::int AS h, count(*) AS n, "
            "avg(c.actual_wait_minutes) AS w FROM queue_tokens t "
            "LEFT JOIN consultations c ON c.clinic_id = t.clinic_id AND c.token_id = t.id "
            "WHERE t.clinic_id = :cid AND t.arrived_at >= :lo AND t.arrived_at < :hi GROUP BY h ORDER BY h",
            lo=lo, hi=hi)]
        weekdays = {int(r.w): int(r.n) for r in self._q(
            "SELECT (extract(isodow FROM arrived_at AT TIME ZONE :tz)::int - 1) AS w, count(*) AS n "
            "FROM queue_tokens WHERE clinic_id = :cid AND arrived_at >= :lo AND arrived_at < :hi GROUP BY w",
            lo=lo, hi=hi)}
        return LoadOut(range=self._range(start, end), by_hour=hours,
                       by_weekday=[WeekdayLoad(weekday=w, arrivals=weekdays.get(w, 0)) for w in range(7)])

    # ----------------------------------------------------- prediction accuracy
    def prediction_accuracy(self, start_date: date | None, end_date: date | None) -> PredictionAccuracyOut:
        start, end, lo, hi = self.window(start_date, end_date)
        rows = self._q(
            "SELECT mv.version AS version, count(*) AS n, avg(pl.abs_error) AS mae, "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY pl.abs_error) AS mdae, "
            "avg(pl.pred_median - pl.actual_wait) AS bias, "
            "avg(((pl.actual_wait BETWEEN pl.pred_lower AND pl.pred_upper))::int) AS coverage, "
            "avg(abs((pl.feature_snapshot->>'expected_work_ahead_min')::float - pl.actual_wait)) AS naive "
            "FROM prediction_logs pl JOIN model_versions mv ON mv.id = pl.model_version_id "
            "WHERE pl.clinic_id = :cid AND pl.actual_wait IS NOT NULL AND pl.predicted_at >= :lo "
            "AND pl.predicted_at < :hi GROUP BY mv.version ORDER BY mv.version", lo=lo, hi=hi)
        versions = [VersionAccuracy(
            model_version=r.version, n=int(r.n), mae_minutes=_f(r.mae), median_abs_error_minutes=_f(r.mdae),
            bias_minutes=_f(r.bias), interval_coverage=_f(r.coverage, 4), naive_baseline_mae_minutes=_f(r.naive))
            for r in rows]
        total = sum(v.n for v in versions)
        return PredictionAccuracyOut(
            range=self._range(start, end), versions=versions, enough_data=total >= MIN_PREDICTIONS,
            note=("Compares each prediction made when a patient joined the queue with the wait that actually "
                  "happened. The model is trained on synthetic data. Below "
                  f"{MIN_PREDICTIONS} completed predictions these figures are anecdotes, not accuracy."))
