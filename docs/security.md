# QueueCare — Security Design (Phase 2)

> Demonstration system, synthetic data only. No regulatory compliance (HIPAA, GDPR, etc.) is claimed and none has been assessed.

## Implemented in Phase 2

| Area | Control | Where |
|---|---|---|
| Passwords | Argon2id, 12–128 char policy, common-password blocklist, rehash-on-login | `core/security.py`, `schemas/auth.py` |
| Sessions | 15-min JWT access token + opaque 7-day refresh token in `HttpOnly` cookies; refresh path-scoped to `/api/v1/auth`; nothing in localStorage | `core/cookies.py` |
| Refresh rotation | Single-use tokens stored as SHA-256 hashes; reuse of a rotated token revokes the whole session | `services/auth_service.py` |
| Server-side revocation | Every request checks the session row, so logout takes effect immediately even for unexpired JWTs | `api/deps.py` |
| CSRF | Signed double-submit token + `Origin` allow-list on cookie-authenticated writes; header-token (Bearer) requests are exempt | `api/deps.py` |
| Brute force | Per-IP rate limits (Redis, in-memory fallback) + per-account lockout (5 failures → 15 min) | `core/ratelimit.py` |
| Enumeration | Identical login errors, dummy hash for unknown users, silent forgot-password, generic duplicate-register error | `auth_service.py` |
| Password reset | Single-use hashed tokens, 30-min expiry, revokes all sessions | `auth_service.py` |
| Tenant isolation | Membership-derived access (never trusts client `clinic_id`), 404 for non-members, PostgreSQL RLS (fail-closed), composite tenant FKs | `api/deps.py`, migration `0001` |
| RLS role | App connects as `queuecare_app` (no superuser, no `BYPASSRLS`, not table owner) | `postgres-init.sh` |
| Platform access | Super-admin has no implicit clinic access; the RLS platform flag is raised only in audited platform routes | `require_super_admin` |
| Audit | Append-only `audit_logs` (app role has no UPDATE/DELETE) | migration, `audit_service.py` |
| Input | Pydantic strict schemas (`extra="forbid"`), parameterised ORM queries, bounded pagination | `schemas/` |
| HTTP hardening | CSP, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `no-store`, HSTS (when secure cookies), body-size limit, explicit CORS origins | `middleware/asgi.py` |
| Errors/logs | Uniform JSON errors, no stack traces or submitted values, JSON logs with secret redaction | `core/errors.py`, `core/logging.py` |
| Config | App refuses to start with placeholder/short/duplicate secrets, wildcard CORS, or insecure production settings | `core/config.py` |

## Added in Phase 3

| Area | Control |
|---|---|
| Object lookups | Every department/doctor/schedule/time-off/membership id is looked up inside the caller's clinic, so another clinic's id returns 404, the same as a missing one |
| Least privilege | Admin: all writes. Receptionist/doctor: read, plus status changes (a doctor only for their own profile). Patients: read active doctors and schedules only |
| Privacy | Doctor responses expose `has_account`, never the linked user's id or email. Time-off reasons are staff-only |
| Mass assignment | Create/update schemas forbid unknown fields (no `clinic_id`, `status`, `is_active` on create) |
| Lock-out protection | The last active clinic administrator cannot be deactivated (clinic row locked to stop two admins deactivating each other) |
| DB-enforced integrity | One doctor profile per account per clinic (unique index); no overlapping schedule windows (GiST exclusion constraint), both race-proof |
| Audit | All clinic-management mutations are recorded in the append-only audit log |

## Trade-offs and assumptions

- **Cookies over localStorage** prevent token theft through XSS but require CSRF handling.
- **Per-request session lookup** costs one indexed query but gives instant revocation.
- **Refresh grace window** (default 5 s) tolerates two browser tabs refreshing at once; set `REFRESH_REUSE_GRACE_SECONDS=0` for strict behaviour.
- **Lockout** can be used to lock a victim out temporarily (a known trade-off); IP rate limits and the generic error limit the damage. Progressive back-off is a Phase 10 hardening item.
- **Dev email**: the mock provider logs reset links only when `APP_ENV=development`.
- **Frontend and API should share a registrable domain** (e.g. `app.example.com` / `api.example.com`) so `SameSite=Lax` cookies work. Cross-site hosting needs `COOKIE_SAMESITE=none` + HTTPS.

## Not yet implemented (honest status)

- Rate limits on non-auth endpoints, per-user limits
- Progressive lockout back-off, breached-password check, MFA
- Dependency scanning: `pip-audit` runs in CI (clean on 2026-11-18); the frontend `npm audit` findings are triaged in [dependency-audit.md](dependency-audit.md)
- Backup/restore procedure (Phase 11)
- Independent security review or penetration test: **none performed**

## Verified vs. not yet run

- The migration, RLS policies, tenant foreign keys, exclusion constraint, token uniqueness and audit immutability were exercised against a real PostgreSQL 16 during development.
- The Python test suite (`backend/tests`) has been written but its results must be confirmed by running `pytest` in the Docker environment (see `docs/setup.md`).

## Phase 4 — Appointments

- **Double booking** is prevented by the database (`appointments_no_doctor_overlap` exclusion constraint), not by application checks. SQLSTATE 23P01 is mapped to HTTP 409. Application checks only produce friendlier errors.
- **Reschedule** is a single transaction (cancel old, insert new); a conflict rolls back and leaves the original appointment untouched.
- **Server-derived timing:** clients send only `starts_at`; duration, buffer and end time come from the doctor's configuration, and `starts_at` must land on the doctor's bookable grid.
- **Visibility:** patients see only their own appointments, doctors only their own schedule, front-desk staff the clinic's. Non-visible and cross-tenant appointments return 404 (no existence leak).
- **Abuse guard:** a patient may hold at most 5 upcoming appointments; patients cannot book for other patients.
- **Cancel/reschedule cutoff** (`cancellation_cutoff_hours`) applies to patients; staff may override.
- All booking actions write append-only audit entries.

## Phase 5 — Queue

- **Integrity in the database (migration 0003):** one live token per patient per doctor per day (`uq_queue_tokens_live_patient`), at most one CALLED/IN_CONSULTATION patient per doctor (`uq_queue_tokens_one_active_per_doctor`), one token per appointment, `source` must agree with `appointment_id`, priority 0–2. The service gives friendly 409s, but the constraints hold under concurrency.
- **Token numbers** come from one atomic counter upsert in the same transaction as the token: no duplicates, no gaps.
- **Roles:** front desk adds walk-ins and checks patients in; doctors act only on their own queue (other doctors' tokens return 404); patients can read only their own tokens (`/queue/mine`, no other patient's name) and may only leave the queue while WAITING.
- **State machine** lives in pure, unit-tested code (`queue_logic.py`); illegal transitions return 409; every transition writes an append-only `queue_token_events` row and an audit entry.
- Checking in, starting, completing, no-show and cancelling keep the linked appointment status in step in the same transaction.
- Known limits: walk-ins require an already-registered patient; no real-time push yet (Phase 6); a cancelled token cannot be re-checked-in for the same appointment (the appointment is cancelled with it).

## Phase 6 — Real-time

- **Authentication:** WebSockets use a 30 s, single-use ticket bound to user, clinic and login session, signed with a key distinct from the access-token key. Access is re-derived from the database at connect time and re-checked periodically; logout, a revoked session, a removed membership or a suspended clinic ends the connection.
- **Authorization:** channels are assigned by the server from the verified role. Clients cannot subscribe to anything; every channel is clinic-scoped, and `emit()` refuses a channel from another clinic.
- **Cross-site WebSocket hijacking:** a browser `Origin` that is not in `BACKEND_CORS_ORIGINS` is refused.
- **Abuse limits:** per-user and per-address connection caps, 256-character client messages, strict message schema (ping only), idle timeout, bounded per-connection queues (slow clients are disconnected), ticket minting rate-limited.
- **Data minimisation:** events carry ids, labels and statuses only; patients receive only their own token's state.
- **Outbox:** `outbox_events` is under row-level security. The relay reads across clinics only through the explicit platform context and does nothing else with it.
- Known limits: ticket in the query string (single-use, 30 s); per-process single-use fallback when Redis is down. See [realtime.md](realtime.md).

## Phase 7 — ML
- Models are LightGBM text files plus a JSON bundle: no pickle/joblib at serving time, so loading a model cannot execute code. Version names are validated (no path separators or leading dots) and the bundle must name the directory it lives in.
- A model trained on a different feature list is refused (train/serve skew guard).
- Training is offline; the API only serves the version named in `ml/models/ACTIVE`. Promotion is deliberate.
- The estimate endpoint reuses the queue read scoping: a patient reaches only their own token (404 otherwise); patients never receive the interval, only the median.
- `prediction_logs` rows carry `clinic_id` and are protected by the same RLS as other tenant tables; features stored are queue counts and timings, no names or contact details.
- Prediction logging is best-effort inside a savepoint and cannot fail a queue action.
- Training data is synthetic only; the loader refuses rows not marked `is_synthetic`.

## Phase 8 - Notifications and analytics
- Analytics are CLINIC_ADMIN-only, clinic-scoped by an explicit filter plus RLS, return aggregates only (no identities), and limit the date range (366 days) to bound query cost.
- A member can read and mark only their own in-app notifications (another member's is a 404); the inbox is also clinic-scoped.
- Email goes only to verified addresses; SMS only for time-critical types. There is no consent/preference store yet (documented gap).
- Message bodies carry no clinical detail. Recipients and bodies are never logged. Provider error text is stored only for our own `ProviderError`; other exceptions store just their class name.
- Notification creation runs in a savepoint inside the triggering transaction and cannot fail the booking/queue action.
- The delivery worker and the reminder scan read across clinics using the explicit platform RLS context (same pattern as the outbox relay), touching only notification rows plus read-only lookups.

## Phase 9 - Advanced features
- Drift, slot-suggestion and simulation endpoints are CLINIC_ADMIN-only; SHAP factors in the estimate are staff-only and absent for patients.
- Simulation inputs are strictly bounded (doctors, days, scenarios) and concurrency-limited (HTTP 429) so a request cannot exhaust CPU.
- Drift reads only this clinic's `prediction_logs`; the model directory name is validated before use. No identities are returned.
- Alternatives reuse the booking rules and are clinic-scoped; nothing is reserved.

## Phase 10 - Hardening
- Per-user throttles on booking, queue writes, analytics and the simulation lab (`app/api/limits.py`); 429 with Retry-After.
- A route-inventory test fails the build if any route answers anonymous callers (outside an explicit allowlist) or reveals a clinic to non-members.
- CI runs lint, the full suite, `pip-audit` and a secret scan. Details and known gaps: [testing-and-hardening.md](testing-and-hardening.md).

## Phase 11 - Deployment
- Production settings validator (HTTPS-only cookies/origins, no placeholders, long distinct secrets) is unit-tested against the shipped template.
- Only the reverse proxy publishes ports; DB, Redis and API sit on an internal network. API runs as non-root, read-only filesystem, no capabilities. `TRUST_PROXY_HEADERS` is enabled only behind Caddy.
- Secrets exist only in the git-ignored `.env.production` (mode 600, generated randomly); `.dockerignore` keeps env files, models and datasets out of images.
- See [deployment.md](deployment.md) for backups, restore drill and known gaps.
