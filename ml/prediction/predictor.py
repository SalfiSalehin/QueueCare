"""Load a trained wait-time model and produce an estimate with a range.

Models are stored as LightGBM's native text format plus a JSON bundle: no pickle, so loading a model
file can never execute code. The bundle lists the exact feature names the model was trained on; the
predictor refuses to load a model whose features differ from the code's `FEATURE_COLUMNS`
(protection against train/serve skew).
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

from ml.preprocessing.features import FEATURE_COLUMNS, FEATURE_LABELS

ACTIVE_POINTER = "ACTIVE"


class ModelLoadError(Exception):
    pass


@dataclass(frozen=True)
class Estimate:
    lower: float     # minutes; roughly the 10th percentile, widened by the calibration offset
    median: float    # minutes
    upper: float     # minutes; roughly the 90th percentile, widened by the calibration offset
    model_version: str


@dataclass(frozen=True)
class Factor:
    feature: str
    label: str
    minutes: float       # how much this factor pushed the median estimate up (+) or down (-), in minutes


@dataclass(frozen=True)
class Explanation:
    """Exact additive breakdown of the median model's raw output (TreeSHAP, computed by LightGBM itself):
    base_minutes + sum(contributions) == raw_minutes. It explains the MODEL, not the real world."""

    base_minutes: float
    raw_minutes: float
    contributions: dict[str, float]

    def top(self, k: int = 3, min_abs_minutes: float = 0.5) -> list[Factor]:
        ranked = sorted(self.contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
        return [Factor(name, FEATURE_LABELS.get(name, name), round(value, 1))
                for name, value in ranked[:k] if abs(value) >= min_abs_minutes]


class Predictor:
    def __init__(self, version: str, bundle: dict, boosters: dict[str, object], offset: float) -> None:
        self.version = version
        self.bundle = bundle
        self._boosters = boosters
        self._offset = offset
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- loading
    @staticmethod
    def active_version(root: Path) -> str | None:
        pointer = Path(root) / ACTIVE_POINTER
        if not pointer.is_file():
            return None
        version = pointer.read_text().strip()
        return version or None

    @classmethod
    def load(cls, root: Path, version: str | None = None) -> Predictor:
        import lightgbm as lgb

        root = Path(root)
        version = version or cls.active_version(root)
        if not version or "/" in version or "\\" in version or version.startswith("."):
            raise ModelLoadError("no active model")
        directory = root / version
        try:
            bundle = json.loads((directory / "bundle.json").read_text())
        except (OSError, ValueError) as exc:
            raise ModelLoadError(f"cannot read bundle for {version}: {exc}") from None
        if bundle.get("version") != version:
            raise ModelLoadError("bundle version does not match its directory")
        if tuple(bundle.get("features", ())) != FEATURE_COLUMNS:
            raise ModelLoadError("model was trained on different features than this code expects")
        try:
            boosters = {name: lgb.Booster(model_file=str(directory / filename))
                        for name, filename in bundle["files"].items()}
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadError(f"cannot load model files for {version}: {exc}") from None
        if set(boosters) != {"q10", "q50", "q90"}:
            raise ModelLoadError("bundle must contain q10, q50 and q90 models")
        return cls(version, bundle, boosters, float(bundle["cqr_offset_minutes"]))

    # ------------------------------------------------------------- prediction
    @staticmethod
    def _row(features: dict[str, float]) -> list[float]:
        if tuple(features) != FEATURE_COLUMNS:
            raise ValueError("features must be exactly FEATURE_COLUMNS in order")
        row = [float(features[name]) for name in FEATURE_COLUMNS]
        if not all(math.isfinite(v) for v in row):
            raise ValueError("features must be finite numbers")
        return row

    def predict(self, features: dict[str, float]) -> Estimate:
        import numpy as np

        x = np.array([self._row(features)], dtype=float)
        with self._lock:                       # keep one Booster call at a time; they are cheap
            raw = [float(self._boosters[q].predict(x)[0]) for q in ("q10", "q50", "q90")]
        low, med, high = sorted(max(0.0, v) for v in raw)     # quantiles must not cross; waits are >= 0
        low, high = max(0.0, low - self._offset), max(med, high + self._offset)
        low = min(low, med)
        return Estimate(round(low, 1), round(med, 1), round(high, 1), self.version)

    def explain(self, features: dict[str, float]) -> Explanation:
        """Which inputs moved the MEDIAN estimate, and by how many minutes (TreeSHAP via LightGBM)."""
        import numpy as np

        x = np.array([self._row(features)], dtype=float)
        with self._lock:
            values = self._boosters["q50"].predict(x, pred_contrib=True)[0]
        contributions = {name: float(v) for name, v in zip(FEATURE_COLUMNS, values[:-1], strict=True)}
        base = float(values[-1])
        return Explanation(base_minutes=base, raw_minutes=base + sum(contributions.values()),
                           contributions=contributions)
