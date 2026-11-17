# Testing and security hardening (Phase 10)

## What was added
| Area | What | Where |
|---|---|---|
| Route inventory | Every API route is enumerated. Anonymous callers must get 401/403 from all but an explicit public allowlist; non-members must get 404 from every clinic-scoped route. A new unprotected route fails the suite. | `tests/security/test_route_inventory.py` |
| Per-user throttles | Booking (60/5 min), queue writes (300/5 min), analytics (120/5 min), simulation (10/5 min), keyed by user, 429 with `Retry-After`. Anonymous calls are rejected before they count. | `app/api/limits.py`, `tests/integration/test_rate_limits.py` |
| N+1 guard | SQL statements per request must not grow with queue length or data volume. | `tests/perf/test_query_counts.py` |
| Latency smoke | Measures p50/p95 on a running stack; asserts nothing (timing asserts are flaky on shared machines). | `scripts/perf_smoke.py` |
| CI | Build, ruff, full pytest against real PostgreSQL, `pip-audit`, gitleaks. | `.github/workflows/ci.yml` |

Existing security tests (Phase 2 onward) are unchanged: token forgery, CSRF/Origin, headers, CORS, body size, SQL-injection payloads, error hygiene, RLS isolation.

## Honest status
* The CI workflow has **not run on GitHub yet**; it mirrors the commands run locally in Docker. Treat the first run as a test of the file.
* `pip-audit` needs network access to a vulnerability database. It was not run by the author; run it yourself:
  `docker compose run --rm backend pip-audit -r /app/backend/requirements.txt`.
* **No Playwright / browser E2E tests**: the frontend does not exist yet, so there is nothing to drive. These come with the frontend; they are not claimed here.
* Not built: progressive lockout back-off (needs a migration; today: 5 failures lock the account for 15 minutes, plus per-IP limits), a WAF/DDoS layer (infrastructure, Phase 11), real email/SMS providers, load testing at scale.
* Memory-based throttles are per process. With Redis configured (`RATE_LIMIT_BACKEND=auto`) they are shared across processes; if Redis is down they fall back to per-process counters rather than failing open.

## Reading the throttle numbers
Budgets are generous on purpose: they stop scripts and runaway clients, not people. Tune them in `app/api/limits.py`.
