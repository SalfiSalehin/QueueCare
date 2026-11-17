"""Train, evaluate and package the wait-time models.

    python -m ml.training.run --seed 42            # full run (a few minutes on CPU)
    python -m ml.training.run --seed 42 --quick    # small, for tests
    python -m ml.training.run --seed 42 --promote  # also make this version the active one

Protocol (nothing here is tuned on the test split):
  * chronological split by working day: 70% train / 15% validation / 15% test
  * baselines and models are fitted on TRAIN only
  * hyperparameters and early stopping use VALIDATION only
  * the interval calibration offset (conformalized quantile regression) uses VALIDATION only
  * TEST is evaluated once, at the end, and reported exactly as measured

All metrics in metrics.json / report.md are produced by this script from the data it generated.
The data is SYNTHETIC: the numbers describe the simulator, not real clinics.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml.data_generation.generate_dataset import write_dataset
from ml.evaluation import metrics as M
from ml.monitoring.reference import build_reference, write_reference
from ml.preprocessing.features import FEATURE_COLUMNS, MONOTONE_INCREASING, TARGET
from ml.training.data import load_dataset, temporal_split

QUANTILES = (0.1, 0.5, 0.9)
NOMINAL_COVERAGE = 0.8
DEFAULT_OUT = Path("ml/models")


@dataclass(frozen=True)
class Profile:
    days: int
    doctors: int
    grid: list[dict]
    rounds: int
    rf_trees: int
    gbr_trees: int
    shap_rows: int


FULL = Profile(
    days=200, doctors=12, rounds=600, rf_trees=200, gbr_trees=300, shap_rows=2000,
    grid=[{"num_leaves": nl, "learning_rate": lr, "min_data_in_leaf": md}
          for nl in (15, 31) for lr in (0.05, 0.1) for md in (20, 60)],
)
QUICK = Profile(days=40, doctors=4, rounds=80, rf_trees=30, gbr_trees=50, shap_rows=100,
                grid=[{"num_leaves": 15, "learning_rate": 0.1, "min_data_in_leaf": 20}])


def _lgb_params(base: dict, objective: str, seed: int, n_jobs: int, alpha: float | None = None) -> dict:
    params = {
        "objective": objective, "seed": seed, "deterministic": True, "force_row_wise": True,
        "num_threads": n_jobs, "verbosity": -1, "feature_pre_filter": False,
        **base,
    }
    if objective != "quantile":      # LightGBM rejects monotone constraints with the quantile objective
        params["monotone_constraints"] = [1 if f in MONOTONE_INCREASING else 0 for f in FEATURE_COLUMNS]
    if alpha is not None:
        params["alpha"] = alpha
    return params


def _fit_lgb(params: dict, train: pd.DataFrame, val: pd.DataFrame, rounds: int) -> lgb.Booster:
    dtrain = lgb.Dataset(train[list(FEATURE_COLUMNS)], train[TARGET], free_raw_data=False)
    dval = lgb.Dataset(val[list(FEATURE_COLUMNS)], val[TARGET], reference=dtrain, free_raw_data=False)
    return lgb.train(params, dtrain, num_boost_round=rounds, valid_sets=[dval],
                     callbacks=[lgb.early_stopping(30, verbose=False)])


def _predict(booster: lgb.Booster, df: pd.DataFrame) -> np.ndarray:
    return booster.predict(df[list(FEATURE_COLUMNS)], num_iteration=booster.best_iteration)


def _round(obj):
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    if isinstance(obj, float | np.floating):
        return round(float(obj), 6)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def run_pipeline(seed: int, out_root: Path = DEFAULT_OUT, quick: bool = False, n_jobs: int = 1,
                 promote: bool = False, work_dir: Path | None = None) -> Path:
    profile = QUICK if quick else FULL
    timings: dict[str, float] = {}
    clock = time.perf_counter()

    def tick(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        timings[name] = round(now - clock, 2)
        clock = now

    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="queuecare-ml-"))
    meta = write_dataset(work, seed=seed, days=profile.days, doctors=profile.doctors)
    df = load_dataset(work / "synthetic_visits.csv.gz")
    split = temporal_split(df)
    tick("generate_and_load")

    train, val, test = split.train, split.val, split.test
    x_cols = list(FEATURE_COLUMNS)
    y_train, y_val, y_test = train[TARGET], val[TARGET], test[TARGET]
    yt = y_test.tolist()

    results: dict[str, dict] = {}

    # ----- baselines: no fitting on the test split
    results["baseline_global_median"] = M.point_report(yt, [float(y_train.median())] * len(test))
    results["baseline_naive_work_ahead"] = M.point_report(yt, test["expected_work_ahead_min"].tolist())

    # ----- comparison models (point predictions)
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(train[x_cols], y_train)
    results["ridge"] = M.point_report(yt, np.clip(ridge.predict(test[x_cols]), 0, None).tolist())
    forest = RandomForestRegressor(n_estimators=profile.rf_trees, min_samples_leaf=5, n_jobs=max(1, n_jobs),
                                   random_state=seed).fit(train[x_cols], y_train)
    results["random_forest"] = M.point_report(yt, forest.predict(test[x_cols]).tolist())
    gbr = GradientBoostingRegressor(n_estimators=profile.gbr_trees, max_depth=4, learning_rate=0.05,
                                    subsample=0.8, random_state=seed).fit(train[x_cols], y_train)
    results["gradient_boosting"] = M.point_report(yt, np.clip(gbr.predict(test[x_cols]), 0, None).tolist())
    tick("baselines_and_sklearn_models")

    # ----- LightGBM: tune on validation with the median objective, then fit all three quantiles
    best = None
    for cfg in profile.grid:
        booster = _fit_lgb(_lgb_params(cfg, "quantile", seed, n_jobs, alpha=0.5), train, val, profile.rounds)
        val_mae = M.mae(y_val.tolist(), _predict(booster, val).tolist())
        if best is None or val_mae < best[0]:
            best = (val_mae, cfg)
    assert best is not None
    chosen = best[1]
    l2_model = _fit_lgb(_lgb_params(chosen, "regression", seed, n_jobs), train, val, profile.rounds)
    results["lightgbm_l2"] = M.point_report(yt, np.clip(_predict(l2_model, test), 0, None).tolist())
    boosters = {q: _fit_lgb(_lgb_params(chosen, "quantile", seed, n_jobs, alpha=q), train, val, profile.rounds)
                for q in QUANTILES}
    tick("lightgbm_tuning_and_fit")

    def triple(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        stacked = np.sort(np.vstack([_predict(boosters[q], df) for q in QUANTILES]), axis=0)  # no crossing
        lo, med, hi = np.clip(stacked, 0, None)
        return lo, med, hi

    lo_val, med_val, hi_val = triple(val)
    offset = M.cqr_offset(y_val.tolist(), lo_val.tolist(), hi_val.tolist(), NOMINAL_COVERAGE)
    lo_test, med_test, hi_test = triple(test)
    results["lightgbm_median_q50"] = M.point_report(yt, med_test.tolist())
    lo_cal, hi_cal = M.apply_interval_offset(lo_test.tolist(), hi_test.tolist(), offset)
    lo_q, hi_q = float(y_train.quantile(0.1)), float(y_train.quantile(0.9))
    intervals = {
        "constant_width_baseline": M.interval_report(yt, [lo_q] * len(test), [float(y_train.median())] * len(test),
                                                     [hi_q] * len(test), NOMINAL_COVERAGE),
        "lightgbm_quantile_raw": M.interval_report(yt, lo_test.tolist(), med_test.tolist(), hi_test.tolist(),
                                                   NOMINAL_COVERAGE),
        "lightgbm_quantile_calibrated": M.interval_report(yt, lo_cal, med_test.tolist(), hi_cal, NOMINAL_COVERAGE),
    }
    buckets = test["people_ahead"].map(M.bucket_people_ahead).tolist()
    hour_buckets = test["hour_of_day"].map(lambda h: f"{int(h):02d}h").tolist()
    slices = {
        "mae_by_people_ahead": M.slice_report(yt, med_test.tolist(), buckets),
        "mae_by_hour": M.slice_report(yt, med_test.tolist(), hour_buckets),
        "mae_by_booked_vs_walkin": M.slice_report(yt, med_test.tolist(),
                                                  test["is_scheduled"].map(lambda v: "booked" if v else "walk-in").tolist()),
        "calibrated_coverage_by_people_ahead": {
            name: {"n": float(len(idx)),
                   "coverage": M.coverage([yt[i] for i in idx], [lo_cal[i] for i in idx], [hi_cal[i] for i in idx])}
            for name, idx in _group_indices(buckets).items()},
    }
    tick("evaluation")

    version = f"lgbm-quantile-s{seed}-{meta['sha256'][:8]}" + ("-quick" if quick else "")
    out_dir = Path(out_root) / version
    out_dir.mkdir(parents=True, exist_ok=True)
    for q, booster in boosters.items():
        booster.save_model(str(out_dir / f"q{int(q * 100)}.txt"), num_iteration=booster.best_iteration)

    shap_note = _shap(boosters[0.5], test, out_dir, profile.shap_rows, seed)
    tick("shap")

    metrics = _round({
        "synthetic": True, "version": version, "seed": seed, "quick": quick, "dataset_sha256": meta["sha256"],
        "dataset_rows": meta["rows"], "split": split.summary, "chosen_lightgbm_params": chosen,
        "best_iterations": {f"q{int(q * 100)}": int(b.best_iteration) for q, b in boosters.items()},
        "cqr_offset_minutes": offset, "nominal_coverage": NOMINAL_COVERAGE,
        "point_models_test": results, "interval_models_test": intervals, "slices_test": slices, "shap": shap_note,
    })
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    bundle = {
        "version": version, "algorithm": "lightgbm-quantile", "synthetic": True, "features": list(FEATURE_COLUMNS),
        "quantiles": list(QUANTILES), "files": {f"q{int(q * 100)}": f"q{int(q * 100)}.txt" for q in QUANTILES},
        "cqr_offset_minutes": round(float(offset), 6), "nominal_coverage": NOMINAL_COVERAGE, "seed": seed,
        "dataset_sha256": meta["sha256"],
        "dataset": {"seed": seed, "days": profile.days, "doctors": profile.doctors}, "trained_at": datetime.now(UTC).isoformat(),
        "test_metrics": {"point": metrics["point_models_test"]["lightgbm_median_q50"],
                         "interval": metrics["interval_models_test"]["lightgbm_quantile_calibrated"]},
        "libraries": {"python": platform.python_version(), "lightgbm": lgb.__version__, "numpy": np.__version__,
                      "pandas": pd.__version__, "scikit-learn": sklearn.__version__},
    }
    (out_dir / "bundle.json").write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    write_reference(out_dir, build_reference({c: train[c].tolist() for c in x_cols}, version=version,
                                              dataset_sha256=meta["sha256"]))      # for drift monitoring
    (out_dir / "timings.json").write_text(json.dumps(timings, indent=2) + "\n")
    (out_dir / "report.md").write_text(render_report(metrics, timings))
    if promote:
        (Path(out_root) / "ACTIVE").write_text(version + "\n")
    return out_dir


def _group_indices(keys: list[str]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    return dict(sorted(groups.items()))


def _shap(booster: lgb.Booster, test: pd.DataFrame, out_dir: Path, rows: int, seed: int) -> dict:
    """Global feature importance for the median model. Failure is reported, not hidden."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import shap

        sample = test[list(FEATURE_COLUMNS)].sample(n=min(rows, len(test)), random_state=seed)
        values = shap.TreeExplainer(booster).shap_values(sample)
        mean_abs = np.abs(values).mean(axis=0)
        ranking = sorted(zip(FEATURE_COLUMNS, mean_abs.tolist(), strict=True), key=lambda kv: -kv[1])
        (out_dir / "shap_importance.json").write_text(json.dumps(dict(ranking), indent=2) + "\n")
        shap.summary_plot(values, sample, show=False)
        plt.tight_layout()
        plt.savefig(out_dir / "shap_summary.png", dpi=150)
        plt.close("all")
        return {"status": "ok", "rows": int(len(sample)), "top_features": [[k, v] for k, v in ranking[:8]]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _table(rows: list[list[str]], header: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def render_report(m: dict, timings: dict) -> str:
    f = lambda v: f"{v:.2f}"  # noqa: E731
    point_rows = [[name, f(r["mae"]), f(r["median_abs_error"]), f(r["rmse"]), f(r["r2"]), f(r["bias"]),
                   f"{r['within_5min']:.1%}", f"{r['within_10min']:.1%}"]
                  for name, r in m["point_models_test"].items()]
    interval_rows = [[name, f"{r['coverage']:.1%}", f(r["mean_width"]), f(r["pinball_q10"]), f(r["pinball_q50"]),
                      f(r["pinball_q90"])] for name, r in m["interval_models_test"].items()]
    slice_blocks = []
    for title, key in (("People ahead", "mae_by_people_ahead"), ("Hour of arrival", "mae_by_hour"),
                       ("Booked vs walk-in", "mae_by_booked_vs_walkin")):
        slice_blocks.append(f"**{title}**\n\n" + _table(
            [[k, str(int(v["n"])), f(v["mae"]), f(v["bias"])] for k, v in m["slices_test"][key].items()],
            ["slice", "n", "MAE (min)", "bias (min)"]))
    cov_rows = [[k, str(int(v["n"])), f"{v['coverage']:.1%}"]
                for k, v in m["slices_test"]["calibrated_coverage_by_people_ahead"].items()]
    shap = m["shap"]
    shap_text = ("Mean |SHAP| (minutes) of the median model, top features:\n\n" + _table(
        [[k, f(v)] for k, v in shap["top_features"]], ["feature", "mean abs SHAP"])
        if shap.get("status") == "ok" else f"SHAP did not run: {shap.get('error')}")
    return f"""# Wait-time model report — `{m['version']}`

> **SYNTHETIC DATA.** Everything below was measured on data produced by this repository's queueing
> simulator. It shows how well a model recovers patterns the simulator contains. It says nothing about
> accuracy in any real clinic.

Generated by `python -m ml.training.run`. Seed {m['seed']}{' (quick profile)' if m['quick'] else ''}.
Dataset: {m['dataset_rows']} rows, SHA-256 `{m['dataset_sha256'][:16]}...`.
Chronological split by day: {json.dumps(m['split'])}.
Test split used once, after all tuning and calibration.

## Point predictions (test split, minutes)

{_table(point_rows, ['model', 'MAE', 'median abs err', 'RMSE', 'R²', 'bias', 'within 5 min', 'within 10 min'])}

MAE and median absolute error are the headline numbers: wait times are heavy-tailed (a few overloaded
doctor-days have very long waits), which inflates RMSE and depresses R² for every model.

## 80% prediction intervals (test split)

Nominal coverage {m['nominal_coverage']:.0%}. "Calibrated" widens the raw q10-q90 interval by
{m['cqr_offset_minutes']:+.2f} min on each side (conformalized quantile regression fitted on the validation
split only).

{_table(interval_rows, ['interval', 'coverage', 'mean width (min)', 'pinball q10', 'pinball q50', 'pinball q90'])}

## Where the median model is weaker (test split)

{chr(10).join(slice_blocks)}

**Calibrated coverage by queue length**

{_table(cov_rows, ['people ahead', 'n', 'coverage'])}

## Explainability

{shap_text}

## Chosen configuration

LightGBM parameters (picked on validation): `{json.dumps(m['chosen_lightgbm_params'])}`;
best iterations: `{json.dumps(m['best_iterations'])}`. Stage timings (seconds): `{json.dumps(timings)}`.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quick", action="store_true", help="small dataset and models (for tests)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--n-jobs", type=int, default=1, help="threads; 1 keeps LightGBM bit-for-bit reproducible")
    parser.add_argument("--promote", action="store_true", help="make this version the active one")
    args = parser.parse_args()
    out = run_pipeline(args.seed, args.out, args.quick, args.n_jobs, args.promote)
    print(f"trained model written to {out}")
    print(f"report: {out / 'report.md'}")
    if not args.promote:
        print(f"not promoted. To serve it: python -m ml.training.promote {out.name}")


if __name__ == "__main__":
    sys.exit(main())
