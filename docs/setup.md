# QueueCare — Development Setup Guide

> Demonstration system. Synthetic data only.

## Prerequisites

| Tool | Required | Notes |
|---|---|---|
| Docker + Docker Compose v2 | Recommended path | Runs the whole stack |
| Git | Yes | |
| Python 3.12 | For running ML/backend outside Docker | Containers pin 3.12 |
| Node.js 22 LTS + npm | For running the frontend outside Docker | |
| PostgreSQL 16 / Redis 7 | Only if not using Docker | |

## 1. Configure environment

```bash
cp .env.example .env
# Generate strong secrets and paste them into .env:
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Replace every `CHANGE_ME_*` value. Keep the password inside `DATABASE_URL`, `MIGRATION_DATABASE_URL` and `REDIS_URL` in sync with the standalone password variables. Never commit `.env`.

## 2. Start the stack (Docker)

```bash
docker compose config --quiet      # validate the compose file and env
docker compose up --build -d
docker compose ps                  # postgres + redis should be "healthy"
docker compose logs -f backend
```

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs (development only) |

> The `frontend` service serves the patient screens at http://localhost:3000. A clinic must exist and be ACTIVE before
> "Find a clinic" lists anything: run `python scripts/demo_walkthrough.py --platform-email <platform admin email>`
> (see the script header). Start everything with `docker compose up -d`.

## 3. Stop / reset

```bash
docker compose down            # stop, keep data
docker compose down -v         # stop and DELETE the database volume
```

## 4. Running without Docker (optional)

```bash
# backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev
```

## 5. Phase 2: build, migrate, test

```powershell
docker compose build backend
docker compose up -d postgres redis
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend pytest -v
```

Tests create and migrate a separate `queuecare_test` database, so your dev data is never touched. Then start the API and open http://localhost:8000/docs:

```powershell
docker compose up -d backend
curl http://localhost:8000/health/ready
```

## 6. Common commands

| Task | Command |
|---|---|
| Run migrations | `docker compose run --rm backend alembic upgrade head` |
| Create platform admin | `docker compose run --rm -e QUEUECARE_ADMIN_PASSWORD=... backend python -m app.cli create-superadmin --email you@example.com` |
| Backend tests | `docker compose run --rm backend pytest` |
| Synthetic end-to-end demo (through the real API) | `python scripts/demo_walkthrough.py --platform-email you@example.com` (see its docstring) |
| Generate dataset, train, promote model | `docker compose run --rm backend python -m ml.training.run --seed 42 --promote` |
| Browser E2E tests | `docker compose --profile e2e run --rm e2e` (needs a platform admin; see [frontend.md](frontend.md)). 33 tests pass in CI (run #10, 2026-11-20) |

## Security notes for developers

- `.env` is git-ignored; only `.env.example` is committed.
- Postgres and Redis ports bind to `127.0.0.1` only.
- Only `NEXT_PUBLIC_*` variables reach the browser. They must never contain secrets.
- The API connects as `queuecare_app` (no `BYPASSRLS`); migrations use the owner role.
