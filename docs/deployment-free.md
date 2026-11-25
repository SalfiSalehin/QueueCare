# Free hosted demo (Vercel + Render + Neon)

> **Status: written, not yet run.** None of this has been tried on the real services. The two code changes it needs (the proxy-hops
> setting and its tests) are in the repository; the files below were written from the project's configuration and the services'
> documentation. Expect to fix small things on the first attempt, and record them here.
>
> This is a demonstration host for a portfolio, not production. It runs on free plans with synthetic data only. For a real
> single-server deployment with HTTPS, backups and a restore drill, see [deployment.md](deployment.md).

## What runs where

| Part | Service | Why |
|---|---|---|
| Web app (Next.js) | Vercel, free plan | Never sleeps, so the first page loads at once. It forwards `/api/v1/*` to the API, so cookies stay on one origin |
| API (FastAPI) | Render, free web service | Builds `backend/Dockerfile.render`; applies migrations on start |
| Database (PostgreSQL 16) | Neon, free plan | Render's own free database is deleted after about 44 days |
| Redis | none | Optional: with one instance the in-memory broker, tickets and rate limits behave correctly |

The live-queue WebSocket connects from the browser straight to the API (`wss://`), because Vercel cannot proxy WebSockets.

## What to expect from free plans (checked 2026-11-22)
* **Render** spins a free service down after 15 minutes without traffic; waking takes about a minute. 750 free instance hours a month are
  shared across the workspace, and the filesystem is wiped on every restart. ([Render free tier](https://render.com/docs/free))
* **Neon** gives 1 GB per project; compute suspends after 5 minutes idle and wakes in a few seconds; 100 compute hours a month.
  Its page does not mention deleting inactive projects, but that was not confirmed. ([Neon free plan](https://neon.com/faqs/free-plan-limits-and-quotas))
* **Vercel**: not checked. Its free plan is meant for personal, non-commercial use, which a portfolio is; check its current terms.
* So the first visit after a quiet period is slow (the API wakes, then the database). Open the site a minute before showing it to anyone.
* The in-memory rate limits and the live-queue tickets reset whenever the API sleeps or restarts. That is harmless for a demo.
* The wait-time model files are not in the repository, so the hosted site uses the honest heuristic estimate (labelled "simple rule").

## Names used below
Pick names first so the addresses are predictable. Replace them everywhere if yours differ.
* Render service: `queuecare-api` giving `https://queuecare-api.onrender.com` (Render adds a suffix if the name is taken; use the address it shows)
* Vercel project: `queuecare` giving `https://queuecare.vercel.app` (same rule)

## Step 1. Create the database and the restricted role (do this before anything is deployed)
1. At neon.com create a project. Choose the region closest to your Render region (for Bangladesh: Asia Pacific, Singapore, for both).
2. On the project page open **Connect**. Turn **Pooled connection** OFF (use the direct address; the pooled one breaks the per-request database
   settings that tenant isolation relies on). Copy the connection string. It looks like
   `postgresql://OWNER:PASSWORD@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`. This is the **owner URL**; keep it private.
3. Make a password for the app role (PowerShell, from the project folder). Letters and digits only, so nothing needs escaping:
   ```powershell
   $appPw = python -c "import secrets; print(secrets.token_hex(24))"
   $appPw
   ```
4. Run the one-time setup file (the local `postgres` container from `docker compose up -d` provides `psql`):
   ```powershell
   Get-Content -Raw infrastructure\hosted\hosted-db-init.sql | docker compose exec -T postgres psql "OWNER-URL-HERE" -v app_password=$appPw
   ```
   Success: it ends with one row `queuecare_app | f | f | f` (not a superuser, cannot create roles, cannot bypass row-level security).
   **If it says `permission denied to create role`**, stop and send me the message; that means this host does not let us create the
   restricted role and we must pick another free database.
5. Write down the two URLs the API needs. Change `postgresql://` to `postgresql+psycopg://` in both:
   * `MIGRATION_DATABASE_URL` = the owner URL
   * `DATABASE_URL` = the owner URL with `OWNER:PASSWORD` replaced by `queuecare_app:` plus `$appPw`

## Step 2. Put the new files on GitHub
Extract the zip over the project, then `git add -A`, commit and push to `main`. Render builds from the repository.

## Step 3. Deploy the API on Render
1. In the Render dashboard choose **New**, then **Blueprint**, connect the `QueueCare` repository and pick `main`. Render reads `render.yaml`.
   (If you prefer, create a **Web Service** by hand instead: runtime Docker, Dockerfile path `./backend/Dockerfile.render`, Docker context `.`,
   plan Free, health check path `/health/ready`, and add every environment variable listed in `render.yaml`.)
2. When it asks for the values marked `sync: false`, enter:
   * `DATABASE_URL` and `MIGRATION_DATABASE_URL` from Step 1
   * `BACKEND_CORS_ORIGINS` = `https://queuecare.vercel.app` (https, no trailing slash, exactly the Vercel address)
   * `FRONTEND_URL` = the same address
3. Deploy. The first build takes several minutes. In the service's **Logs**, look for `Running upgrade` lines (the migrations) and then
   `Uvicorn running`. Failure to start with a message about a missing role means Step 1 was skipped.
4. Test: open `https://queuecare-api.onrender.com/health/ready` in a browser. Expect `{"status":"ok", ...}`; the first call may take a minute.

## Step 4. Deploy the web app on Vercel
1. At vercel.com choose **Add New Project**, import the same repository, and set **Root Directory** to `frontend`. Framework: Next.js (detected).
2. Add these environment variables (for Production) **before** the first deploy, because Next.js reads them while building:

   | Name | Value |
   |---|---|
   | `API_INTERNAL_URL` | `https://queuecare-api.onrender.com` |
   | `NEXT_PUBLIC_API_BASE_URL` | `/api/v1` |
   | `NEXT_PUBLIC_WS_URL` | `wss://queuecare-api.onrender.com` |
   | `NEXT_PUBLIC_DEMO_MODE` | `true` |
3. Deploy. If Vercel gives the project a different address than `queuecare.vercel.app`, go back to Render and change
   `BACKEND_CORS_ORIGINS` and `FRONTEND_URL` to the real one (the service restarts by itself).

## Step 5. Create the platform admin and the showcase data
Run these from the project folder, with the stack from `docker compose up -d` available for the container. Use a strong password.
```powershell
$env:QUEUECARE_ADMIN_PASSWORD = "<a strong password you choose>"
docker compose run --rm -e MIGRATION_DATABASE_URL="OWNER-URL-WITH-+psycopg" -e QUEUECARE_ADMIN_PASSWORD backend python -m app.cli create-superadmin --email platform@example.com
python scripts/demo_walkthrough.py --base https://queuecare-api.onrender.com --origin https://queuecare.vercel.app --platform-email platform@example.com --showcase
```
The script prints four sign-in addresses at the end (password `Demo-Clinic-Passw0rd!2026`, synthetic). Registration is limited to 10 per hour
per visitor address, and each run registers four users.

### Adding more clinics
Signed in, **My clinics** has a **Register a clinic** button. The clinic starts as waiting for approval; sign in as the platform admin
(**Platform**) and approve it, and it then appears in **Find a clinic**. Running the walkthrough script again also makes a new clinic each time.
(The button and its browser test were added after the first hosted run; their test results are recorded in the README only once run.)

## Step 6. Check it by hand
- [ ] `https://queuecare.vercel.app` loads and shows the yellow "synthetic data only" banner.
- [ ] Sign in as the patient from Step 5; open **Find a clinic**, search "lake", open the clinic, look at Appointments.
- [ ] Sign in (private window) as the receptionist; the queue board shows "Live updates on". Add a walk-in and watch the patient's queue page change.
- [ ] Sign out; reload; a protected page sends you to sign-in (cookies work through the proxy).
- [ ] After 20 minutes of no use, open the site again: it should work after about a minute.
- [ ] Try 11 sign-ups from one device within an hour: the 11th is refused (the limit is per visitor, not shared by everyone).

## If something fails
| Symptom | Likely cause |
|---|---|
| API logs: `Application role queuecare_app does not exist` | Step 1 not run on this database |
| API will not start; message names `JWT_SECRET`, `COOKIE_SECURE` or an origin | A required setting is wrong; the check refuses to start on purpose |
| Sign-in works then you are signed out at once | `BACKEND_CORS_ORIGINS`/`FRONTEND_URL` is not exactly the Vercel address |
| Page loads but every action says network error | `API_INTERNAL_URL` wrong or the API is still waking; wait a minute and retry |
| "Live updates" never turns on | `NEXT_PUBLIC_WS_URL` missing or not `wss://`; it is read at build time, so redeploy on Vercel after changing it |
| Everyone is rate limited together | `TRUSTED_PROXY_HOPS` is 1 instead of 2 |
| Database errors right after a quiet period | Neon waking; retry (the pool checks connections before use) |

## Updating, pausing and removing
* **Update**: push to `main`; Render and Vercel rebuild by themselves. Migrations run on each API start.
* **Pause**: suspend the Render service from its page; the Vercel site then shows errors, so also remove the link from your CV.
* **Remove**: delete the Render service, the Vercel project and the Neon project. Nothing else holds data.
* **Secrets**: they live only in the three dashboards. If one leaks, change it there and redeploy; none is in git.
