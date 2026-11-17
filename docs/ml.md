# Wait-time prediction (Phase 7)

> **Everything here is trained on synthetic data produced by a simulator in this repository.** No real
> patient data is used anywhere. Any number a model produces describes the simulator, not a real clinic.
> Accuracy figures below were produced by running `ml.training.run` (seed 42, full run) and are copied
> exactly as measured; the complete generated report is [ml-report-seed42.md](ml-report-seed42.md).

## What it predicts

For a patient who is **waiting**, the estimated minutes until their consultation starts, as a median plus
an 80% range (staff and doctors see the range; patients see only the median).

## Pipeline

| Step | Code | Notes |
|---|---|---|
| Synthetic data | `ml/data_generation/simulator.py`, `generate_dataset.py` | Discrete-event queue simulation. Deterministic for a seed. Default run (12 doctors × 200 working days) yields ~64k rows (a test asserts ≥ 30k). Output `ml/datasets/synthetic_visits.csv.gz` + `dataset_meta.json` (seed, row count, SHA-256). Every row has `is_synthetic=True`; the loader refuses data that is not marked. |
| Features | `ml/preprocessing/features.py` | One function turns a `QueueSnapshot` (the queue at the moment of arrival) into the model row. **The API uses the same function**, so there is no train/serve skew. A model whose feature list differs from the code is refused at load time. |
| Split | `ml/training/data.py` | Chronological by working day: 70% train / 15% validation / 15% test. Row-level random splits would put near-copies of the same day's queue in both train and test. |
| Baselines | `ml/training/run.py` | Global median; naive "people ahead × doctor's recent mean". |
| Models | `ml/training/run.py` | Ridge, RandomForest, GradientBoosting, LightGBM (L2), LightGBM quantile (q10/q50/q90). |
| Tuning | validation only | Small grid on validation MAE; early stopping on validation. The test split is never used to choose anything. |
| Intervals | `ml/evaluation/metrics.py` | Conformalized quantile regression: the q10–q90 interval is widened (or narrowed) by an offset computed on **validation only**, targeting 80% coverage. Reported next to a constant-width baseline and the raw quantiles. |
| Explainability | SHAP on the median model | Written next to the model. |
| Serving | `ml/prediction/predictor.py`, `backend/app/services/prediction_service.py` | LightGBM native text files + `bundle.json`. **No pickle**, so loading a model cannot execute code. |

## Leakage controls

- Features use only what is known when the patient arrives. No start time, wait, or consultation length of the patient's own visit.
- Chronological split by day; labels never inform features.
- Tests: no feature named after a post-arrival quantity; no single feature with |correlation| ≥ 0.95 to the target; a model fitted on **shuffled labels** must not beat the global-median baseline by more than a small margin.
- Monotone constraints (more work ahead never shortens a wait) are applied to the L2 LightGBM comparison model only: LightGBM does not allow them with the quantile objective, so the served q10/q50/q90 models are unconstrained. The test checks a coarse trend instead of strict monotonicity.

## Measured results (seed 42, full run, test split, synthetic data)

Version `lgbm-quantile-s42-4dbad111`; 64,164 rows (train 44,991 / validation 9,540 / test 9,633, split by day).

| model | MAE (min) | median abs err (min) | within 5 min |
|---|---|---|---|
| global median baseline | 16.05 | 4.23 | 64.6% |
| naive "people ahead × recent mean" | 9.13 | 1.82 | 67.7% |
| Ridge | 8.65 | 4.26 | 54.7% |
| LightGBM L2 | 7.90 | 2.64 | 62.4% |
| **LightGBM median (served)** | **7.37** | **1.75** | **70.0%** |

80% interval on the test split (nominal 80%): constant-width baseline covers 90.7% with mean width 43.4 min;
the served LightGBM interval covers **87.0%** with mean width **23.4 min**.

What these numbers do and do not say:
- The served model is the best of those compared on MAE, but its edge over the naive baseline is modest: median error 1.75 vs 1.82 min. Most of the predictive signal is simply "how many people are ahead".
- It **under-predicts long queues**: with 6+ people ahead (n=114) MAE is 60 min and bias −47 min; with 3–5 ahead MAE is 32 min. Walk-ins (MAE 16.3) are far harder than booked patients (3.4).
- The median model has a negative bias overall (−3.35 min): with heavy-tailed waits, a median sits below the mean. Its RMSE (19.8) is worse than the L2 models (18.6–18.7); R² 0.73.
- **Interval calibration did nothing here**: the conformal offset computed on validation was exactly 0.00 minutes, so "calibrated" equals "raw". About 37% of visits have nobody ahead and a wait of 0, which piles scores at exactly 0 and pins the 80th-percentile offset there. As a result coverage is 87% overall (100% when nobody is ahead, 79.8% for 1–2 ahead, 77.5% for 3–5) but only **67.5% for 6+ ahead**: the interval is too narrow exactly where waits are long. Calibrating separately by queue length would be the natural fix; it has not been done.
- All of this is the simulator measuring itself. Do not quote these as accuracy of QueueCare in a real clinic.

## Running it

```bash
docker compose build backend
docker compose run --rm backend python -m ml.training.run --seed 42 --promote   # full run, minutes on CPU
docker compose run --rm backend pytest -v
```

Training writes `ml/models/<version>/` (`bundle.json`, `metrics.json`, `report.md`, `q10|q50|q90.txt`, SHAP output).
**Training never changes what the API serves.** Serving uses the version named in `ml/models/ACTIVE`, written
by `--promote` or `python -m ml.training.promote <version>`. `--quick` trains a tiny model for tests.
The `ml/models` and `ml/datasets` folders are git-ignored.

## How the API uses it

- `GET /api/v1/clinics/{cid}/queue/tokens/{token_id}/estimate` (any clinic member; a patient can only reach their own token, otherwise 404).
- Response `source`: `model`, `heuristic` (no model loaded, or it failed: people ahead × the doctor's recent mean, no range) or `not_waiting`. The API never labels a heuristic number as a model prediction.
- When a patient joins the queue (walk-in or check-in) and a model is active, the prediction is stored in `prediction_logs`; when the consultation starts, the real wait and absolute error are filled in. Logging runs in a savepoint and is best-effort: a failure never blocks a queue action.
- The first time a model is used it is registered in `model_versions` and marked active.

## Known limitations (read before trusting any number)

- The simulator encodes the rules its author wrote down. A model can only learn what the generator contains; results say nothing about real clinics.
- The simulated wait distribution is heavy-tailed, and some simulated doctors are chronically overloaded. Mean-based metrics are dominated by those cases; read MAE next to the median absolute error and the per-slice tables in `report.md`.
- The model is trained on predictions **at arrival**. `GET .../estimate` evaluates the queue *as it is now* with the same model, which is an approximation for patients who have already waited a while (time already waited is not a feature). A model trained on "remaining wait at any moment" would be the next improvement.
- Interval coverage was calibrated on a validation split from the same simulator, and (see above) the calibration offset came out as 0 and long queues are under-covered; under distribution shift it will not hold.
- Prediction logs let you compare predictions with actuals later, but no automatic monitoring, drift alerts or retraining job exists yet.

## Where the numbers come from

`ml/models/<version>/metrics.json` and `report.md` are written by `ml.training.run` from the data it generates.
The section above quotes the seed-42 full run; rerunning with the same seed and code reproduces `metrics.json` exactly (tested on the quick profile).

## Phase 9 additions
Training now also writes `reference.json` (binned training-feature distributions) and records dataset details in the
bundle. For an earlier model: `docker compose run --rm backend python -m ml.monitoring.reference <version>`.
See [advanced.md](advanced.md) for explanations, drift and the simulation lab.
