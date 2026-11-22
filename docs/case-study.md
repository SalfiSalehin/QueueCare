# Case study: building QueueCare

*Written for portfolio and interview use. Every number here is from this repository's own test and training runs.*

## The problem
Clinics lose time to long, unpredictable waits and double-booked slots. QueueCare explores a backend that keeps many
clinics strictly separated, never double-books, runs a live queue, predicts how long a waiting patient will wait,
and shows staff why.

## What I built
- A multi-tenant API (about 70 HTTP endpoints plus a WebSocket) on FastAPI and PostgreSQL 16, with isolation enforced
  by row-level security and booking integrity enforced by an exclusion constraint.
- A queue state machine with real-time updates through a transactional outbox and Redis pub/sub.
- A wait-time model (LightGBM quantile regression) trained on a synthetic queue simulator, served with SHAP
  explanations, drift monitoring and an honest heuristic fallback.
- Notifications with idempotent delivery (mock providers), admin analytics, slot-length advice and a simulation lab.
- A hardened production stack (HTTPS proxy, non-root read-only containers, backups and a restore drill) and a test
  suite of 452 backend tests, including a route inventory that fails if any endpoint is left unprotected.

## The numbers (synthetic data, seed 42)
The served model's median error is 1.75 minutes against 1.82 for a naive baseline: a small win, because most of the
signal is "how many people are ahead". It under-predicts long queues (MAE 60 minutes with 6+ ahead) and its 80%
interval covers 87% overall but only 67.5% for long queues. Calibration changed nothing (offset exactly 0.0).
I reported these as measured and documented why, instead of tuning until they looked better.

## Problems found by testing, and what they taught me
| Problem | How it surfaced | Fix and lesson |
|---|---|---|
| LightGBM refused monotone constraints with the quantile objective | First real training run crashed | Constraints only where the objective supports them; documented. Read library limits before designing around a feature |
| WebSocket tests failed intermittently (`CancelledError` during client disconnect) | Flaky tests across runs; I inspected the Starlette 1.10 test-client source | Made server-side cleanup cancellation-safe and made the test helper wait for the connection to drop. Flakiness was a real shutdown race, not bad luck |
| A booking conflict returned HTTP 500 instead of 409 | Failing concurrency test after adding notifications | The notification savepoint was swallowing the database's constraint error; flush first, then isolate the notification. A savepoint can hide the failure you most need to see |
| Analytics tests passed in the morning and failed at noon | They depended on the time of day (a cancelled slot fell inside "today") | Tests now use data far outside every range. Time-dependent tests are bugs waiting for a schedule |
| My route-inventory security test **passed while checking zero routes** | I distrusted a green result and asserted that the sweep found routes | It really had found none (wrong object); rewrote it and added a minimum-count assertion. A test that cannot fail proves nothing |
| `/health/ready` said "degraded" on a healthy system | Found while rehearsing the deployment, not by any test | The status came from an unset response field. Added the missing test. Rehearsing a deployment finds bugs unit tests do not |
| Proxy crash-looped on an empty config value | Same rehearsal | Empty and unset environment variables are different; defaults must cover both |

## Decisions worth discussing
See [decisions.md](decisions.md): why RLS plus an exclusion constraint, why an outbox, why cookies not localStorage,
why synthetic data is labelled everywhere, why mocks.

## What is missing
No frontend, no real notification providers, no real-host deployment, no real-clinic validation of the model. Full
list: [limitations.md](limitations.md). The most valuable next steps would be a thin frontend over the existing API,
calibrating prediction intervals by queue length, and running the CI workflow and `pip-audit` for the first time.

## Accurate ways to describe this work
- "Designed and built a multi-tenant clinic queue API (FastAPI, PostgreSQL row-level security, exclusion constraints) with 452 automated tests against a real database."
- "Implemented a quantile wait-time model with SHAP explanations and drift monitoring, trained on a synthetic simulator, and documented its measured limits (including interval under-coverage for long queues)."
- "Built idempotent notification delivery (transactional enqueue, leases, backoff) and a rehearsed production stack with backup and restore drills."

Avoid claiming real-clinic accuracy, a deployed product, HIPAA/GDPR compliance, or a user interface.
