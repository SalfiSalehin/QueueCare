"""Model drift report for the clinic admin (read-only).

Compares the inputs of recent live predictions with the training-time reference (PSI per feature) and
the recent prediction error with the error measured at training. Both are alarms, not verdicts: see
ml/monitoring/drift.py. Everything is scoped to the clinic in context.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.core.config import get_settings
from app.core.errors import ServiceError
from app.schemas.analytics import DriftOut, FeatureDrift, PerformanceDrift
from ml.monitoring.drift import (
    MIN_SAMPLES, bin_counts, performance_status, psi, status as psi_status,
)
from ml.prediction.predictor import Predictor
from ml.preprocessing.features import FEATURE_COLUMNS, FEATURE_LABELS

MAX_WINDOW_DAYS = 90
MAX_ROWS = 5000
MIN_PERFORMANCE_SAMPLES = 30
_ORDER = {"stable": 0, "moderate": 1, "high": 2}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


class DriftService:
    def __init__(self, db: Session, tenant: TenantContext, now: datetime | None = None) -> None:
        self.db = db
        self.cid = tenant.clinic.id
        self._now = now
        self.model_dir = Path(get_settings().ml_model_dir)

    def report(self, days: int) -> DriftOut:
        if not 1 <= days <= MAX_WINDOW_DAYS:
            raise ServiceError(422, f"days must be between 1 and {MAX_WINDOW_DAYS}.")
        empty = dict(window_days=days, samples=0, overall=None, features=[], performance=None)
        version = Predictor.active_version(self.model_dir)
        if version is None or "/" in version or "\\" in version or version.startswith("."):
            return DriftOut(status="no_model", model_version=None, note="No trained model is active.", **empty)
        directory = self.model_dir / version
        reference = _read_json(directory / "reference.json")
        if reference is None or reference.get("version") != version:
            return DriftOut(
                status="no_reference", model_version=version, **empty,
                note=f"No training reference for this model. Create it with: python -m ml.monitoring.reference {version}")
        bundle = _read_json(directory / "bundle.json") or {}

        since = (self._now or datetime.now(UTC)) - timedelta(days=days)
        rows = list(self.db.execute(text(
            "SELECT pl.feature_snapshot AS snap, pl.abs_error AS err FROM prediction_logs pl "
            "JOIN model_versions mv ON mv.id = pl.model_version_id "
            "WHERE pl.clinic_id = :cid AND mv.version = :v AND pl.predicted_at >= :since "
            "ORDER BY pl.predicted_at DESC LIMIT :lim"),
            {"cid": self.cid, "v": version, "since": since, "lim": MAX_ROWS}))
        snapshots = [r.snap for r in rows]
        errors = [float(r.err) for r in rows if r.err is not None]
        performance = self._performance(errors, bundle)
        if len(snapshots) < MIN_SAMPLES:
            return DriftOut(
                status="insufficient_data", model_version=version, window_days=days, samples=len(snapshots),
                overall=None, features=[], performance=performance,
                note=f"Only {len(snapshots)} live predictions in the window; at least {MIN_SAMPLES} are needed "
                     "for a meaningful comparison.")
        features: list[FeatureDrift] = []
        for name in FEATURE_COLUMNS:
            values = [float(s[name]) for s in snapshots if name in s]
            spec = reference["features"].get(name)
            if spec is None or len(values) < MIN_SAMPLES:
                continue
            score = psi(spec["proportions"], bin_counts(spec, values))
            features.append(FeatureDrift(feature=name, label=FEATURE_LABELS.get(name, name),
                                         psi=round(score, 4), status=psi_status(score)))
        features.sort(key=lambda f: f.psi, reverse=True)
        overall = max((f.status for f in features), key=lambda s: _ORDER[s], default=None)
        return DriftOut(
            status="ok", model_version=version, window_days=days, samples=len(snapshots), overall=overall,
            features=features, performance=performance,
            note="PSI compares recent inputs with the synthetic training data (below 0.10 stable, 0.10-0.25 "
                 "moderate, above 0.25 large). Input drift is an alarm to investigate, not proof the model is "
                 "wrong; stable inputs do not prove it is right. The reference error comes from the synthetic test set.")

    @staticmethod
    def _performance(errors: list[float], bundle: dict[str, Any]) -> PerformanceDrift:
        reference_mae = ((bundle.get("test_metrics") or {}).get("point") or {}).get("mae")
        if len(errors) < MIN_PERFORMANCE_SAMPLES:
            return PerformanceDrift(n=len(errors), recent_mae_minutes=None,
                                    reference_mae_minutes=None if reference_mae is None else round(float(reference_mae), 2),
                                    status="insufficient_data")
        recent = sum(errors) / len(errors)
        if reference_mae is None:
            return PerformanceDrift(n=len(errors), recent_mae_minutes=round(recent, 2),
                                    reference_mae_minutes=None, status="unknown")
        return PerformanceDrift(n=len(errors), recent_mae_minutes=round(recent, 2),
                                reference_mae_minutes=round(float(reference_mae), 2),
                                status=performance_status(recent, float(reference_mae)))
