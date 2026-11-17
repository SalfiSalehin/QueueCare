# Advanced features (Phase 9)

Five features built on the Phase 7 model and Phase 8 data. None needs a database migration. All ML-related
data is **synthetic**; every response that depends on it says so.

| Feature | Endpoint | Who | What it is |
|---|---|---|---|
| Explanations | `GET /clinics/{cid}/queue/tokens/{id}/estimate` (`factors`, `typical_minutes`) | staff only | Which inputs moved the median estimate, in minutes |
| Alternative doctors | `GET /clinics/{cid}/doctors/{id}/alternatives` | any member | Other doctors with the earliest bookable slots |
| Drift monitoring | `GET /clinics/{cid}/analytics/drift?days=` | clinic admin | Have live inputs/errors moved away from training? |
| Slot-length suggestions | `GET /clinics/{cid}/analytics/scheduling-suggestions?days=` | clinic admin | Advice on each doctor's slot length |
| Simulation lab | `POST /clinics/{cid}/simulation` | clinic admin | "What if" runs on the synthetic simulator |

## Explanations (SHAP)
LightGBM's native TreeSHAP (`pred_contrib=True`) is applied to the **median (q50)** model. Contributions are
additive: `base + sum(contributions) = raw model output` (tested). The API returns the largest factors with
plain-language labels and minutes. They are shown only to staff and only when the estimate came from the model
(never for the heuristic fallback, never to patients). Limits: SHAP explains the *model*, not the real world;
the model was trained on synthetic data; the interval (q10/q90) is not explained.

## Alternative doctors
Reuses the normal slot rules (schedules, time off, existing appointments, notice, horizon), so a suggested slot
is one that could be booked. Doctors with no slot, off duty or inactive are left out; candidates are capped at 25
per request; ties go to the same department. Nothing is reserved: the patient books through the usual endpoint.

## Drift monitoring
* **Input drift:** Population Stability Index per feature, comparing the last N days of this clinic's live
  `prediction_logs` snapshots with the training rows in `reference.json`
  (<0.10 stable, 0.10-0.25 moderate, >0.25 high; at least 100 predictions needed).
* **Performance drift:** recent MAE (predictions whose actual wait is known, at least 30) against the MAE
  measured on the held-out synthetic test split (ok up to 1.25x, watch up to 1.5x, otherwise degraded).
* `reference.json` is written by training. For a model trained earlier, build it once:
  `docker compose run --rm backend python -m ml.monitoring.reference <version>`; it regenerates the data from the
  seed and refuses to write unless the dataset SHA-256 matches the one recorded at training.
* Honest reading: PSI is an alarm to investigate, not proof the model is wrong; stable inputs do not prove it is right.
  The reference is synthetic, so a real clinic will legitimately look "different" at first.

## Slot-length suggestions
Plain statistics, not ML: the shortest 5-minute slot (10-60) that fits 80% of a doctor's completed consultations
in the window. Needs at least 30 consultations. Status `lengthen`, `shorten` (only if at least 10 minutes shorter
would do), `keep`, or `insufficient_data`. Advice only: nothing is changed automatically.

## Simulation lab
Runs the Phase 7 queue simulator with the admin's parameters (doctors 1-6, days 5-30, service length, slot length,
booked share, walk-ins per hour; up to 3 scenarios, deltas against the first). It is deterministic per seed.
Cost is bounded by those limits and a per-process semaphore (2 concurrent runs, otherwise HTTP 429).
**It does not forecast your clinic.** The inputs are synthetic assumptions, and because each doctor has their own
queue, adding doctors only increases the sample size; it cannot model hiring staff.

## Security notes
Admin-only endpoints return aggregates, no identities. Strict request schemas with hard bounds. Explanations are
staff-only. Alternatives are clinic-scoped (RLS plus explicit filters). No new secrets or settings.

## Tests
`tests/unit/test_scheduling_logic.py`, `tests/ml/test_monitoring_and_lab.py` (pure; no DB or LightGBM),
`tests/ml/test_explain.py` (additivity, reference), `tests/integration/test_phase9.py` (API, roles, isolation, bounds).
