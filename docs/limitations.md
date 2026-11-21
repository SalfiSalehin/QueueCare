# Limitations and known gaps

Read this before relying on anything in QueueCare. It is the honest counterpart to the README.

## Not built
- **Patient profile on join (fixed and verified 2026-11-17).** Joining a clinic now creates the person's patient profile there, so reception can find them and their own "My queue" shows their tokens. The 441 backend tests pass and the browser tests pass with the old workaround removed. People who joined before the fix get their profile the next time they join or at their first booking.
- **Frontend.** Patient, staff (queue board, live updates) and admin (insights, simulation lab) screens exist and were used by hand; 36 browser tests (including 17 phone-width checks) pass on the development stack (also run in CI), and the production web-app image was built and run on a local rehearsal stack, never on a real host. The clinic setup screens (doctors, hours, time off, team) are covered by the browser tests. The platform-admin screens (approve, suspend and reopen clinics) pass their browser tests on the development stack and in CI; the clinic search on Find a clinic (name or address words, paged) passes its browser tests on the development stack (backend, unit and browser tests pass locally and in CI), and cannot search by place or specialty because clinics have no such fields; no screenshots, nothing tested on phones or other browsers, and there is no public demo ([frontend.md](frontend.md)).
- **Real notification providers.** Email and SMS are mocks; nothing is ever delivered. No user notification preferences or consent records; staff are not notified.
- **Production readiness.** Never deployed to a real host. No monitoring, alerting, log shipping, automatic off-site backups, staging environment or zero-downtime deploys. The CI workflow runs on GitHub (run #10 on 2026-11-20: backend tests and `pip-audit`, frontend type-check/unit tests/build, the 33 browser tests, the production-stack build and start, and a secret scan all pass). After the framework upgrades `npm install` reports 0 npm vulnerabilities (see [dependency-audit.md](dependency-audit.md)); `npm audit` is not yet a CI gate.
- **Auth gaps.** No progressive lockout back-off (5 failures lock an account for a fixed 15 minutes), no MFA, no breached-password check (only a tiny blocklist), email verification does not gate login, and because the email provider is a mock, no verification or password-reset message is actually delivered.
- **Throttling.** Per-IP limits on auth endpoints and per-user limits on a few expensive ones; no global or WAF-level protection.

## Machine learning
- **Synthetic data only.** The training data comes from a queue simulator written by the same author. Reported accuracy measures the simulator, not any real clinic; real-world performance is unknown and could be much worse.
- **Modest gain.** Median error 1.75 vs 1.82 minutes for a naive "people ahead × recent mean" baseline; most signal is simply how many people are ahead.
- **Long queues.** With 6+ people ahead (n=114 in the test split) MAE is 60 minutes with a −47 minute bias.
- **Interval calibration.** The conformal offset computed was exactly 0.0, so "calibrated" equals "raw"; coverage is 87% overall (nominal 80%) but 67.5% for long queues.
- **Drift monitoring** compares live inputs to the synthetic training reference, so a real clinic will look "different" at first. PSI is an alarm to investigate, not proof the model is wrong.
- **Simulation lab** is a what-if on assumptions you supply. It cannot model adding staff because doctors do not share patients in the simulator.

## Data and compliance
- No real patient data should ever be used. No compliance (HIPAA, GDPR, local law) is claimed or assessed; there is no data-retention or deletion workflow, no consent management and no encryption of individual fields beyond what the database volume provides.
- Audit logging exists for clinic administration actions, not for every read.

## Engineering
- Single-process background workers (outbox relay, notification worker) run inside each API container; safe to replicate (idempotent, `SKIP LOCKED`) but delivery is at-least-once.
- Rate-limit counters fall back to per-process memory if Redis is down.
- Test suite uses a real database and takes about 8 minutes; there are no load tests beyond query-count guards and an optional latency script.
- Some FastAPI/Pydantic deprecation warnings remain in test output (an `httpx` notice and `alias` warnings); they are harmless today and should be cleaned up.
