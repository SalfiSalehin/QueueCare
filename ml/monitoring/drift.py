"""Data-drift measurement (pure standard library).

Population Stability Index (PSI) compares how a feature was distributed when the model was trained
(the reference) with how it is distributed in recent live predictions. Rules of thumb from credit-risk
practice, used here only as a rough alarm: PSI < 0.10 stable, 0.10-0.25 moderate shift, > 0.25 large.

Drift in INPUTS does not by itself mean the model is wrong, and stable inputs do not prove it is right;
the API therefore reports performance drift (recent error vs the error measured at training) separately.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence
from typing import Any

MAX_CATEGORIES = 10      # features with at most this many distinct values are binned by value
N_QUANTILE_BINS = 10
EPS = 1e-4               # floor for empty bins so the logarithm stays finite
STABLE_PSI = 0.10
HIGH_PSI = 0.25
MIN_SAMPLES = 100        # below this, a PSI is too noisy to report


def build_feature_reference(values: Sequence[float]) -> dict[str, Any]:
    """Bin definition plus the training-time share of rows in each bin."""
    if not values:
        raise ValueError("cannot build a reference from no values")
    distinct = sorted(set(values))
    if len(distinct) <= MAX_CATEGORIES:
        spec: dict[str, Any] = {"kind": "values", "points": distinct}
    else:
        ordered = sorted(values)
        edges = sorted({ordered[min(len(ordered) - 1, (len(ordered) * i) // N_QUANTILE_BINS)]
                        for i in range(1, N_QUANTILE_BINS)})
        spec = {"kind": "edges", "points": edges}
    counts = bin_counts(spec, values)
    spec["proportions"] = [round(c / len(values), 6) for c in counts]
    return spec


def _bin(spec: dict[str, Any], value: float) -> int:
    points = spec["points"]
    if spec["kind"] == "values":
        try:
            return points.index(value)
        except ValueError:
            return len(points)                       # a value never seen in training: its own "other" bin
    return bisect_left(points, value)                # v <= edge belongs to that edge's bin


def bin_counts(spec: dict[str, Any], values: Sequence[float]) -> list[int]:
    counts = [0] * (len(spec["points"]) + 1)
    for value in values:
        counts[_bin(spec, value)] += 1
    return counts


def psi(expected: Sequence[float], actual_counts: Sequence[int]) -> float:
    if len(expected) != len(actual_counts):
        raise ValueError("expected and actual must have the same number of bins")
    total = sum(actual_counts)
    if total <= 0:
        raise ValueError("no live values to compare")
    score = 0.0
    for e_raw, count in zip(expected, actual_counts, strict=True):
        e, a = max(e_raw, EPS), max(count / total, EPS)
        score += (a - e) * math.log(a / e)
    return score


def status(psi_value: float) -> str:
    if psi_value < STABLE_PSI:
        return "stable"
    return "moderate" if psi_value < HIGH_PSI else "high"


def performance_status(recent_mae: float, reference_mae: float) -> str:
    """Recent error against the error measured on the held-out test data at training time."""
    if reference_mae <= 0:
        return "unknown"
    ratio = recent_mae / reference_mae
    if ratio <= 1.25:
        return "ok"
    return "watch" if ratio <= 1.5 else "degraded"
