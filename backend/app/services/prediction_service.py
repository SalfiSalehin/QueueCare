"""Wait-time estimates and the prediction log.

Honesty rules
- If no trained model is promoted (or it fails to load), estimates fall back to a plain queueing
  heuristic (people ahead x the doctor's recent average consultation) and say so (`source="heuristic"`,
  no range). The API never pretends a model produced a number.
- The model is trained on SYNTHETIC data; responses carry a note saying so.
- Prediction is best-effort: any failure while logging a prediction is swallowed (inside a savepoint)
  and never blocks or breaks a queue action.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.config import get_settings
from app.models import Consultation, Doctor, ModelVersion, PredictionLog, QueueToken
from app.permissions.roles import ACTIVE_TOKEN_STATUSES
from app.services.queue_logic import Entry
from ml.prediction.predictor import Explanation, ModelLoadError, Predictor
from ml.preprocessing.features import QueueSnapshot, features_from_snapshot, percentile

log = logging.getLogger("queuecare.ml")
_ACTIVE = [s.value for s in ACTIVE_TOKEN_STATUSES]
RECENT_CONSULTATIONS = 10
SYNTHETIC_NOTE = ("Estimate from a statistical model trained on synthetic demonstration data. "
                  "Real waiting times will vary.")
HEURISTIC_NOTE = "Rough estimate (people ahead x the doctor's recent average). No trained model is active."

_cache_lock = threading.Lock()
_cache: dict[str, tuple[str, Predictor | None]] = {}


def get_predictor(model_dir: str) -> Predictor | None:
    """The currently promoted model, loaded once per version. None if there is none or it is unusable."""
    version = Predictor.active_version(Path(model_dir))
    if version is None:
        return None
    with _cache_lock:
        cached = _cache.get(model_dir)
        if cached is not None and cached[0] == version:
            return cached[1]
    try:
        predictor: Predictor | None = Predictor.load(Path(model_dir), version)
    except (ModelLoadError, ImportError) as exc:
        log.warning("ML model %s could not be loaded: %s", version, exc)
        predictor = None
    with _cache_lock:
        _cache[model_dir] = (version, predictor)
    return predictor


@dataclass(frozen=True)
class EstimateResult:
    median: float
    lower: float | None
    upper: float | None
    source: str                       # "model" | "heuristic"
    model_version: str | None
    features: dict[str, float]


class PredictionService:
    def __init__(self, db: Session, tenant: TenantContext, now: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.clinic_id = tenant.clinic.id
        self.tz = ZoneInfo(tenant.clinic.timezone)
        self._now = now or (lambda: datetime.now(UTC))
        self.model_dir = get_settings().ml_model_dir

    @property
    def available(self) -> bool:
        return get_predictor(self.model_dir) is not None

    # ---------------------------------------------------------------- features
    def snapshot(self, *, token: QueueToken, doctor: Doctor, appt_start: datetime | None,
                 ahead: list[Entry], as_of: datetime) -> QueueSnapshot:
        """The queue as seen by a patient at `as_of`, using only information available at that moment."""
        local = as_of.astimezone(self.tz)
        scheduled_ahead = sum(1 for e in ahead if e.source == "APPOINTMENT")
        active = self.db.execute(select(QueueToken.started_at, QueueToken.called_at).where(
            QueueToken.clinic_id == self.clinic_id, QueueToken.doctor_id == doctor.id,
            QueueToken.status.in_(_ACTIVE))).first()
        in_service = active is not None
        elapsed = 0.0
        if active is not None and active.started_at is not None:
            elapsed = max(0.0, (as_of - active.started_at).total_seconds() / 60.0)
        recent = [float(d) for d in self.db.scalars(
            select(Consultation.duration_minutes).where(
                Consultation.clinic_id == self.clinic_id, Consultation.doctor_id == doctor.id,
                Consultation.duration_minutes.is_not(None))
            .order_by(Consultation.ended_at.desc()).limit(RECENT_CONSULTATIONS))]
        arrivals = self.db.scalar(select(func.count()).select_from(QueueToken).where(
            QueueToken.clinic_id == self.clinic_id, QueueToken.doctor_id == doctor.id,
            QueueToken.arrived_at >= as_of - timedelta(minutes=30), QueueToken.arrived_at <= as_of,
            QueueToken.id != token.id)) or 0
        scheduled = token.source == "APPOINTMENT" and appt_start is not None
        return QueueSnapshot(
            arrival_minute_of_day=local.hour * 60 + local.minute + local.second / 60.0,
            day_of_week=local.weekday(), is_scheduled=scheduled,
            lateness_min=(token.arrived_at - appt_start).total_seconds() / 60.0 if scheduled else 0.0,
            priority=token.priority, n_scheduled_ahead=scheduled_ahead,
            n_walkin_ahead=len(ahead) - scheduled_ahead,
            sched_slot_minutes_ahead=float(scheduled_ahead * doctor.default_slot_minutes),
            in_service=in_service, elapsed_in_service_min=elapsed,
            doctor_recent_mean_service=(sum(recent) / len(recent)) if recent else None,
            doctor_recent_p80_service=percentile(recent, 0.8) if recent else None,
            slot_minutes=float(doctor.default_slot_minutes), arrivals_last_30min=int(arrivals),
        )

    # ---------------------------------------------------------------- estimate
    def estimate(self, snapshot: QueueSnapshot) -> EstimateResult:
        features = features_from_snapshot(snapshot)
        predictor = get_predictor(self.model_dir)
        if predictor is not None:
            try:
                est = predictor.predict(features)
                return EstimateResult(est.median, est.lower, est.upper, "model", est.model_version, features)
            except Exception:  # noqa: BLE001
                log.exception("model prediction failed; using the heuristic")
        return EstimateResult(round(features["expected_work_ahead_min"], 1), None, None, "heuristic", None, features)

    def explain(self, features: dict[str, float]) -> Explanation | None:
        """What moved the median estimate (None without a model or if explaining fails)."""
        predictor = get_predictor(self.model_dir)
        if predictor is None:
            return None
        try:
            return predictor.explain(features)
        except Exception:  # noqa: BLE001
            log.exception("could not explain the prediction")
            return None

    # -------------------------------------------------------------- prediction log
    def _model_version_id(self, predictor: Predictor) -> uuid.UUID:
        existing = self.db.scalar(select(ModelVersion.id).where(ModelVersion.version == predictor.version))
        if existing is not None:
            return existing
        self.db.execute(update(ModelVersion).where(ModelVersion.is_active.is_(True)).values(is_active=False))
        bundle: dict[str, Any] = predictor.bundle
        row = ModelVersion(
            id=uuid.uuid4(), version=predictor.version, algorithm=str(bundle.get("algorithm", "lightgbm-quantile")),
            metrics=bundle.get("test_metrics", {}), feature_schema={"features": bundle.get("features", [])},
            artifact_ref=f"ml/models/{predictor.version}", is_active=True,
            trained_at=datetime.fromisoformat(str(bundle["trained_at"])))
        self.db.add(row)
        self.db.flush()
        return row.id

    def log_arrival(self, *, token: QueueToken, doctor: Doctor, appt_start: datetime | None,
                    ahead: list[Entry]) -> None:
        """Record what the model predicted when this patient joined, so it can be compared with the
        actual wait later. Does nothing without a model. Never raises."""
        predictor = get_predictor(self.model_dir)
        if predictor is None:
            return
        try:
            with self.db.begin_nested():                       # savepoint: failure must not poison the txn
                started = time.perf_counter()
                now = self._now()
                snap = self.snapshot(token=token, doctor=doctor, appt_start=appt_start, ahead=ahead, as_of=now)
                features = features_from_snapshot(snap)
                est = predictor.predict(features)
                self.db.add(PredictionLog(
                    id=uuid.uuid4(), clinic_id=self.clinic_id, token_id=token.id,
                    model_version_id=self._model_version_id(predictor), pred_lower=est.lower,
                    pred_median=est.median, pred_upper=est.upper, feature_snapshot=features, predicted_at=now,
                    latency_ms=int((time.perf_counter() - started) * 1000)))
                self.db.flush()
        except Exception:  # noqa: BLE001
            log.exception("could not log the arrival prediction")


def record_actual_wait(db: Session, clinic_id: uuid.UUID, token_id: uuid.UUID, actual_minutes: float) -> None:
    """When the consultation starts, complete the token's prediction row with the real wait."""
    db.execute(update(PredictionLog).where(
        PredictionLog.clinic_id == clinic_id, PredictionLog.token_id == token_id,
        PredictionLog.actual_wait.is_(None)
    ).values(actual_wait=actual_minutes, abs_error=func.abs(PredictionLog.pred_median - actual_minutes)))
