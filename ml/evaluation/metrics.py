"""Evaluation metrics. Standard library only, so they are unit-tested without numpy and cannot
silently depend on a library's conventions. Inputs are plain sequences of numbers.

Everything here is applied to the held-out TEST split exactly once, after model selection.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from ml.preprocessing.features import percentile


def _check(y: Sequence[float], p: Sequence[float]) -> None:
    if len(y) != len(p) or len(y) == 0:
        raise ValueError("y and prediction must be the same non-zero length")


def mae(y: Sequence[float], p: Sequence[float]) -> float:
    _check(y, p)
    return sum(abs(a - b) for a, b in zip(y, p, strict=True)) / len(y)


def rmse(y: Sequence[float], p: Sequence[float]) -> float:
    _check(y, p)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(y, p, strict=True)) / len(y))


def median_abs_error(y: Sequence[float], p: Sequence[float]) -> float:
    _check(y, p)
    return percentile([abs(a - b) for a, b in zip(y, p, strict=True)], 0.5)


def bias(y: Sequence[float], p: Sequence[float]) -> float:
    """Mean of (prediction - actual): positive means the model over-estimates waits."""
    _check(y, p)
    return sum(b - a for a, b in zip(y, p, strict=True)) / len(y)


def r2(y: Sequence[float], p: Sequence[float]) -> float:
    _check(y, p)
    mean = sum(y) / len(y)
    total = sum((a - mean) ** 2 for a in y)
    if total == 0:
        return 0.0
    return 1.0 - sum((a - b) ** 2 for a, b in zip(y, p, strict=True)) / total


def share_within(y: Sequence[float], p: Sequence[float], minutes: float) -> float:
    _check(y, p)
    return sum(1 for a, b in zip(y, p, strict=True) if abs(a - b) <= minutes) / len(y)


def pinball(y: Sequence[float], q_pred: Sequence[float], alpha: float) -> float:
    """Pinball (quantile) loss for quantile level alpha. Lower is better."""
    _check(y, q_pred)
    total = 0.0
    for a, b in zip(y, q_pred, strict=True):
        diff = a - b
        total += alpha * diff if diff >= 0 else (alpha - 1) * diff
    return total / len(y)


def coverage(y: Sequence[float], lower: Sequence[float], upper: Sequence[float]) -> float:
    """Share of actual values that fall inside [lower, upper]."""
    _check(y, lower)
    _check(y, upper)
    return sum(1 for a, lo, hi in zip(y, lower, upper, strict=True) if lo <= a <= hi) / len(y)


def mean_width(lower: Sequence[float], upper: Sequence[float]) -> float:
    _check(lower, upper)
    return sum(hi - lo for lo, hi in zip(lower, upper, strict=True)) / len(lower)


def cqr_offset(y: Sequence[float], lower: Sequence[float], upper: Sequence[float], target: float = 0.8) -> float:
    """Conformalized quantile regression offset (Romano et al., 2019).

    Computed on a CALIBRATION split (validation, never test): widen [lower, upper] by this amount on
    each side (negative = narrow) to reach `target` coverage on exchangeable future data. The score of
    a point is how far it lies outside its interval (negative if inside).
    """
    _check(y, lower)
    _check(y, upper)
    scores = sorted(max(lo - a, a - hi) for a, lo, hi in zip(y, lower, upper, strict=True))
    n = len(scores)
    rank = min(n, math.ceil((n + 1) * target))     # finite-sample corrected rank
    return scores[rank - 1]


def apply_interval_offset(lower: Sequence[float], upper: Sequence[float], offset: float) -> tuple[list[float], list[float]]:
    lo = [max(0.0, a - offset) for a in lower]
    hi = [max(b + offset, a) for a, b in zip(lo, upper, strict=True)]
    return lo, hi


def point_report(y: Sequence[float], p: Sequence[float]) -> dict[str, float]:
    return {
        "mae": mae(y, p), "rmse": rmse(y, p), "median_abs_error": median_abs_error(y, p), "r2": r2(y, p),
        "bias": bias(y, p), "within_5min": share_within(y, p, 5.0), "within_10min": share_within(y, p, 10.0),
    }


def interval_report(y: Sequence[float], lower: Sequence[float], median: Sequence[float],
                    upper: Sequence[float], nominal: float = 0.8) -> dict[str, float]:
    return {
        "nominal_coverage": nominal, "coverage": coverage(y, lower, upper), "mean_width": mean_width(lower, upper),
        "pinball_q10": pinball(y, lower, 0.1), "pinball_q50": pinball(y, median, 0.5),
        "pinball_q90": pinball(y, upper, 0.9),
    }


def slice_report(y: Sequence[float], p: Sequence[float], keys: Sequence[object],
                 label: Callable[[object], str] = str) -> dict[str, dict[str, float]]:
    """MAE, bias and count per slice (e.g. per queue-length bucket), to show where a model is weak."""
    _check(y, p)
    groups: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(label(k), []).append(i)
    return {name: {"n": float(len(idx)), "mae": mae([y[i] for i in idx], [p[i] for i in idx]),
                   "bias": bias([y[i] for i in idx], [p[i] for i in idx])}
            for name, idx in sorted(groups.items())}


def bucket_people_ahead(value: object) -> str:
    n = int(float(value))  # type: ignore[arg-type]
    if n == 0:
        return "0"
    if n <= 2:
        return "1-2"
    if n <= 5:
        return "3-5"
    return "6+"
