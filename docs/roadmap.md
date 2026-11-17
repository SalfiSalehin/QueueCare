# QueueCare — Implementation Roadmap

Each phase follows the same loop: purpose → modules → DB changes → security review → implement → test → verify → document. Phase gate = all tests green and approval before the next phase.

| Phase | Scope | Exit criteria |
|---|---|---|
| **1. Foundation** ✅ verified | Repo, folder structure, Docker Compose, env/secrets config, architecture + DB design docs, setup guide | Compose config validates; docs reviewed |
| **2. Database & Auth** ✅ 76/76 tests passing | Alembic baseline, extensions, all core tables, RLS, Argon2id, JWT + rotating refresh tokens, CSRF, rate limiting, RBAC, tenancy dependency | Auth + tenant-isolation + security tests green |
| **3. Clinic Management** ✅ 136/136 tests passing | Clinic registration/approval, departments, doctors, staff, schedules, time off, audit logging | CRUD + RBAC + isolation tests |
| **4. Appointments** ✅ 178/178 tests passing | Slot calculation, booking, cancel, reschedule, exclusion constraint | Concurrent-booking test: exactly one winner, rest HTTP 409 |
| **5. Queue** ✅ 227/227 tests passing | Walk-in, token allocation, state machine, event log, doctor workflow, policy | Token uniqueness under concurrency; transition tests |
| **6. Real-time** ✅ 268/268 tests passing | WS tickets, gateway, Redis Pub/Sub, outbox relay, reconnect, dedupe | WS authz tests; no event loss after simulated crash |
| **7. AI/ML** ✅ 309/309 tests passing | Synthetic generator (≥30k rows), preprocessing, baseline, LR/RF/GBR/LightGBM, quantile models, evaluation, serving, prediction logs | Reproducible training; measured metrics reported as-is; ML tests |
| **8. Analytics & Notifications** ✅ 370/370 tests passing | Tenant-scoped analytics, doctor utilisation, prediction accuracy, mock providers, worker with retries/idempotency | Analytics isolation + notification idempotency tests |
| **9. Advanced** ✅ 413/413 tests passing | Adaptive scheduling, simulation lab, SHAP, drift monitoring, doctor-availability suggestions | Each feature documented and tested |
| **10. Testing & Security** ✅ 425/425 tests passing (no Playwright: no frontend yet; pip-audit not yet run) | Full pytest, Playwright E2E, security suite, perf checks, dependency scanning | CI fully green |
| **11. Deployment** ✅ 436/436 tests; stack, backup and restore drill rehearsed locally (not on a real host; CI job never run) | Prod Dockerfiles, Vercel + backend host + managed PG/Redis, migrations, HTTPS, backups | Deployed smoke test |
| **12. Portfolio** 🔨 docs written; awaiting review | README, limitations, decisions, case study, demo walkthrough script. **No screenshots or public demo: no frontend exists** | Reviewed against "no invented results" rule |

## Frontend track (started after Phase 12)

F1 (foundation, auth, patient screens) type-checks and its patient flow was verified by hand (2026-11-14); F2 staff queue board with WebSocket was used by hand (2026-11-15); F3 admin screens (insights, simulation lab, estimate explanation) were used by hand and are covered by the browser tests (2026-11-16); F4: the 14 Playwright browser tests pass on the dev stack (2026-11-16); the production frontend image was built and run behind Caddy locally and checked by hand, including live updates through `/ws` (2026-11-16). Original plan: design system and layout shell (Phase 1–2), auth pages (2), role dashboards (3–5), live queue UI (6), analytics charts (8), simulation/explainability UI (9), landing page (12).

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| RLS + connection pooling leaking tenant context | `SET LOCAL` inside each transaction; tests that assert context resets |
| Lost real-time events | Transactional outbox; clients re-sync via REST on reconnect |
| Free-tier hosting lacks Redis/WebSocket support | Document limits; polling fallback in frontend |
| Synthetic-data ML overstating real-world accuracy | Label as synthetic everywhere; report honestly |
| Scope size | Strict phase gates; advanced features only after core is stable |

## Assumptions

- A patient has one global login and one `patients` profile per clinic.
- Walk-in patients may be registered by staff without a user account.
- Each department has a token prefix (A, B, C…); sequences reset daily per clinic.
- Default slot 15 min + 5 min buffer, configurable per doctor and clinic.
