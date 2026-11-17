# Deployment (Phase 11; web app added in F4)

Host-neutral: one Linux machine with Docker Compose v2 runs the whole stack. This is the simplest setup that keeps
WebSockets, Redis and PostgreSQL row-level security working, which many free "serverless" tiers do not.

> **Honest status.** Nothing here has been deployed to a real host. The stack (including the web app behind Caddy) was started and
> used end to end on a local Docker Desktop rehearsal (2026-11-16). Rehearse locally (below) again before any real host.
> QueueCare uses **synthetic data and mock notification providers**; do not put real patient data into it.

## Layout
```
Internet -> Caddy (80/443, automatic HTTPS)
              /api/*, /health/*  -> backend (FastAPI, 1 worker, read-only filesystem)  -> postgres (volume)
                                                                                      -> redis
              everything else    -> frontend (Next.js standalone server, read-only filesystem)
migrate (one-shot, owner role) runs `alembic upgrade head` before backend starts
```
* Only Caddy publishes ports. PostgreSQL, Redis, the API and the web app live on an `internal` network with no route out.
* The browser talks to one origin. The web app calls `/api/v1/...` on the same host and Caddy sends it to the API, so session
  cookies are same-origin and the CSRF cookie is readable. The live-updates WebSocket also goes through Caddy (`/api/v1/ws`).
  (When a real email/SMS provider is added, the API will need outbound access; that is a deliberate future change.)
* The API connects as the least-privilege role (no BYPASSRLS, not table owner); only `migrate` uses the owner role.
* Containers drop all Linux capabilities and cannot gain privileges (Redis and Caddy excepted; see comments in the file).

## Files
| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Production stack (postgres, redis, migrate, backend, frontend, caddy, on-demand backup) |
| `frontend/Dockerfile` | `prod` target: `next build` with `output: "standalone"`, runs as the non-root `node` user. Building needs internet (npm packages and Google Fonts) |
| `backend/Dockerfile` | `prod` target (no reload) and `dev` target (default) |
| `infrastructure/deployment/Caddyfile` | HTTPS reverse proxy: `/api/*`, `/health/*`, `/ws` to the API; everything else to the web app |
| `.env.production.example` | Template; `scripts/generate-secrets.sh` fills the secrets |
| `scripts/backup.sh`, `scripts/restore-check.sh` | Backups and restore drill |

## 1. Rehearse locally (do this first)
On Docker Desktop (PowerShell works for compose; the helper scripts are bash: use WSL or Git Bash):
```
copy .env.production.example .env.production
# edit .env.production: DOMAIN=localhost, ACME_EMAIL= (empty), BACKEND_CORS_ORIGINS=https://localhost, FRONTEND_URL=https://localhost
# If Windows refuses ports 80/443 ("forbidden by its access permissions"): HTTP_PORT=8080, HTTPS_PORT=8443 and use
# https://localhost:8443 in BACKEND_CORS_ORIGINS, FRONTEND_URL and every URL below.
bash scripts/generate-secrets.sh
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.production ps
curl.exe -k https://localhost/health/ready
```
Then open `https://localhost/` (or `https://localhost:8443/` if you changed the ports) in a browser: you should see the landing page, and
registering and signing in should work. The first build takes several minutes (it compiles the web app). Browser tests for this
stack are not provided; the dev-stack browser tests are described in [frontend.md](frontend.md).
Caddy issues a certificate from its own local CA, so the browser/curl warns; `-k` skips that for the rehearsal only.
Stop with `docker compose -f docker-compose.prod.yml --env-file .env.production down` (add `-v` to also delete data).

> Caddy's global `email` falls back to a placeholder when `ACME_EMAIL` is empty (local rehearsal only). Set a real address on a real host.

## 2. First deploy on a real host
1. A VPS (Linux, Docker + Compose v2 installed), a domain, and a DNS A/AAAA record pointing at it. Open ports 80 and 443 only.
2. Clone the repository; `cp .env.production.example .env.production`; set `DOMAIN`, `ACME_EMAIL`, `BACKEND_CORS_ORIGINS`, `FRONTEND_URL` (https only).
3. `bash scripts/generate-secrets.sh`; store `.env.production` in a password manager (it is git-ignored and mode 600).
4. `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
5. Create the first platform admin: `docker compose -f docker-compose.prod.yml --env-file .env.production run --rm -e QUEUECARE_ADMIN_PASSWORD='...' backend python -m app.cli create-superadmin --email you@example.com`. Then register a clinic through the API (see `docs/setup.md`) and check `https://DOMAIN/health/ready`.

## 3. Updating and rollback
* Update: `git pull`, **run `scripts/backup.sh` first**, then `docker compose ... up -d --build`. `migrate` runs automatically and the API starts only if it succeeds.
* Migrations are forward-only. To roll back code, check out the previous tag and rebuild; if a migration must be undone, restore the pre-update backup (data written since is lost) or write a new corrective migration. Never edit an applied migration.
* Zero-downtime upgrades are not provided: expect a few seconds of interruption while the API container restarts.

## 4. Backups and restore drill
* `scripts/backup.sh [keep_days]` writes `backups/queuecare-<UTC time>.dump` (pg_dump custom format) and prunes old files. Schedule it daily with cron on the host.
* A backup on the same disk is not a backup: copy `./backups` to another machine or object storage (encrypt it; it contains personal data in any real use).
* On Windows without Git Bash/WSL use `powershell -ExecutionPolicy Bypass -File scripts\restore-check.ps1 <dump>` (same drill). `scripts/restore-check.sh <dump>` restores into a throw-away database, prints row counts next to the live ones, then drops it. **Run it after the first backup and then regularly.**
* Redis holds only rate-limit counters, WebSocket tickets and pub/sub; it is intentionally not persisted or backed up.

## 5. ML models
The `ml_models` volume is mounted read-only at `/app/ml/models`. It starts empty, so estimates use the labelled heuristic
fallback until you train and promote a model (see `docs/ml.md`) and copy the bundle into the volume. Never fake a model.

## 6. Scaling and operations notes
* One uvicorn worker per container **on purpose**: the outbox relay and notification worker run in every process. They use `FOR UPDATE SKIP LOCKED` and idempotency keys, so extra replicas are safe (at-least-once delivery), but each adds duplicate polling. Scale horizontally with more containers only if needed; one is plenty for a demo.
* Rate limits are shared through Redis; if Redis is down they fall back to per-process counters (never fail open).
* `TRUST_PROXY_HEADERS=true` is set only in this file, because Caddy is the sole entry point. Never set it when the API is directly reachable, or clients can spoof their IP.
* Logs go to stdout (`docker compose logs`). No log shipping or metrics stack is included.

## 7. Hosting choices (none required)
| Option | Fits? |
|---|---|
| Single VPS + this compose file | Recommended: everything works, one bill, you control backups |
| Managed PostgreSQL | Possible: point `DATABASE_URL`/`MIGRATION_DATABASE_URL` at it and create the two roles yourself (see `infrastructure/docker/postgres-init.sh`); remove the `postgres` service |
| Free serverless tiers | Usually poor: no long-lived WebSockets, no Redis, cold starts. The frontend could go on Vercel later; the API should not |

## 8. Pre-launch checklist
- [ ] Rehearsal passed locally; `/health/ready` returns ok over HTTPS and the landing page and sign-in work in a browser
- [ ] For a real domain, add an HSTS header in the Caddyfile (`header Strict-Transport-Security "max-age=31536000"`). It is not in the file because HSTS also pins `localhost`, which would break the local rehearsal
- [ ] `.env.production` has no CHANGE_ME, is not in git, and is backed up in a password manager
- [ ] First backup taken **and restored** with `restore-check.sh`
- [ ] Only ports 80/443 open; SSH keys only; OS updates on
- [ ] `pip-audit` clean or findings triaged; CI green on GitHub
- [ ] `DEMO_MODE=true` and synthetic data only; no real patient data

## Not built / not verified
The web app image has been built and run locally behind Caddy (2026-11-16: pages, sign-in, API, WebSocket live updates checked by hand, with the demo script run via `--insecure`); never on a real host, no browser tests against the production stack, no staging environment, no monitoring/alerting, no log shipping,
no automatic off-site backups, no real email/SMS provider, no zero-downtime deploys, no autoscaling, and the stack has not
been run on a real host. The CI `production-stack` job is new and has never run.
