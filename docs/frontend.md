# Frontend (F1 patient screens, F2 staff queue board)

> **Status: verified by hand on the author's machine (2026-11-14).** `npm run typecheck` is clean (strict mode).
> In a browser, against the dev stack seeded by `scripts/demo_walkthrough.py`: register, sign in, find and join a clinic,
> book a slot, cancel a booking, view appointments, and "My queue" (empty state before check-in) all worked.
> The unit-test result (`npm test`, 9 tests) was reported 8/9 before a config fix and still needs one confirming run.
> Not verified: the live queue view with an active token (needs the staff screens to check a patient in), other browsers,
> mobile layouts, accessibility audits. There are no automated browser tests yet.

Next.js 16 (App Router, Turbopack) + React 19 + TypeScript (strict), Tailwind CSS 4, react-hook-form + zod 4, TanStack Query. Framework upgrades and how each was checked: [dependency-audit.md](dependency-audit.md).
Light "clean clinical" theme (teal on white), system fonts, keyboard-friendly, visible focus, labelled form fields,
`prefers-reduced-motion` respected. Every page repeats that this is a synthetic-data demonstration.

>
> **F2 (staff queue board) status: partly verified by hand (2026-11-15).** In a browser, a receptionist saw the board with
> "Live updates on", added a walk-in, and the patient's "My queue" page showed the new token. Not yet confirmed: typecheck and
> unit-test output for F2, the call/start/complete buttons, the doctor login view, and that pushes (not polling) updated the
> patient. Beyond that, only its pure logic
> (WebSocket client protocol handling and back-off, event de-duplication, URL building, which action buttons each role
> sees) was run, in a stand-in test harness in the author's sandbox (16 checks passed). Run the commands below and
> report what you see. F1 above is the part verified by hand.

## F4: browser tests and the production image
> **Status (2026-11-16): the 14 browser tests pass against the development stack.** The first run passed 12 and failed 2 (the
> queue tests) because of a real gap, not a test typo: a patient record is created at the first booking, not at joining, so
> the seeded patient was not findable by reception (see [limitations.md](limitations.md)). After the setup was changed to book
> once, all 14 passed. **The production image was then built and run behind Caddy locally (2026-11-16): landing page, registration, sign-in, API routing, the demo script and live board updates (a doctor's action appeared on the receptionist's board without refresh) all worked over HTTPS. Not tested: a real host, phones, other browsers.**
> **Follow-up (2026-11-17, verified):** joining a clinic now creates the patient profile (backend: 441 tests pass). The browser-test setup no longer books once to work around it, and with the e2e image's stale copy of the tests fixed (the e2e service now mounts `frontend/e2e`; build once with `docker compose --profile e2e build e2e`) all 16 browser tests pass, including the two queue tests that depend on it. A stronger warm-up in the setup (a signed-in browser visits the main pages first) stopped the first test missing its wait after a restart. The app also has a favicon (`src/app/icon.svg`).
> Because these tests drive the staff board, the live connection, the insights tabs and the simulation lab in a real browser,
> they also cover the main paths of F2 and F3; the tests do not check how the pages look.

**Browser tests** (`frontend/e2e/`, Playwright with Chromium) run against the development stack through the real API:
| File | What it covers |
|---|---|
| `public.spec.ts` | landing page and its sign-up link, redirect to sign-in for protected pages, a wrong password gives one generic message, client-side password check, the API refuses anonymous requests |
| `patient.spec.ts` | a new person registers, joins the seeded clinic, books the furthest-away time, cancels it, sees an empty queue; sign-out locks the app |
| `queue.spec.ts` | a walk-in goes reception -> doctor (call, start, complete) in three browser sessions and the patient's own screen follows every step; requires the live connection badge on the reception board; staff can open the estimate explanation; doctors have no "Remove" |
| `access.spec.ts` | patients are turned away from the board; receptionists have no insights; the **server** answers 403 to analytics for a patient and a receptionist and 404 for a clinic you do not belong to; the admin walks every insights tab and runs the simulation lab |

A global setup creates one clinic per run through the API (four users, platform-admin approval, staff, a doctor with a weekly
schedule, a joined patient) and saves each user's cookies, so tests do not use up the login rate limit. The container shares the
frontend's network namespace, so the browser sees the app at `http://localhost:3000` (the origin the API's CORS and CSRF rules expect),
and a small forwarder lets it reach the API's WebSocket at `localhost:8000`.

Run it (PowerShell; the dev stack must be up, and a platform admin must exist):
```
docker compose up -d postgres redis backend frontend
docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" FLUSHALL'     # dev only: clears the sign-up rate limit
$env:E2E_PLATFORM_EMAIL = "platform2@example.com"
$env:QUEUECARE_ADMIN_PASSWORD = "<the platform admin's password>"
docker compose --profile e2e build e2e
docker compose --profile e2e run --rm e2e
```
A report is written to `frontend/e2e-results/report/index.html` and failure traces and screenshots to `frontend/e2e-results/artifacts/`.
Each run registers 5 users and registration is limited to 10 per hour, hence the Redis flush between runs. Type-check the tests with
`docker compose run --rm --no-deps frontend npm run typecheck:e2e`.

What these tests do **not** cover: other browsers, phone layouts, accessibility audits, visual regressions, the production stack,
password reset (no page exists), two patients racing for one slot (covered by backend tests), and load.

**Production image.** `frontend/Dockerfile` has a `prod` stage (Next.js `output: "standalone"`, non-root, read-only filesystem in
compose) and `docker-compose.prod.yml` runs it behind Caddy next to the API. See [deployment.md](deployment.md). Built and run locally behind Caddy (2026-11-16); never on a real host.

## F3: admin screens (clinic admins only)
> **Status: the simulation lab was used by hand and the browser tests walk every insights tab and run the lab (2026-11-16); the per-tab numbers have not been reviewed with real data, and the author has not reported a type-check for F3.** Pure logic (date ranges, number formatting, bar sizing,
> scenario validation) passed 31 checks in a stand-in harness in the author's sandbox. Run the commands below and report what you see.

| Route | What it shows |
|---|---|
| `/app/c/{id}/insights` | Tabs: **Overview** (appointments, no-show and cancellation rates, walk-in share, median and 90th-percentile wait, visits per day, status breakdowns), **Doctors** (patients seen, wait, booked and busy utilisation), **Busy times** (arrivals by hour and weekday), **Estimate quality** (drift of the model's inputs and error, and past accuracy against a simple rule), **Slot advice** (suggested slot lengths, advice only). Range: last 7, 30 or 90 days in clinic time. |
| `/app/c/{id}/simulation` | Edit up to 3 what-if scenarios for a synthetic clinic and compare waits. Bounds mirror the API and the server re-validates. Same seed means same result. |
| Queue board, waiting row | "Wait estimate" opens the staff explanation: the range, whether it came from a model or a simple rule, and what moved it up or down. |

Honesty rules built into these screens: a missing number is a dash, never zero; the API's own notes (for example "not enough data")
are shown; accuracy with fewer than 30 predictions carries a warning; the model is described as trained on simulated data; the
simulation lab says it is synthetic. Charts are plain CSS bars, so there is no charting library to trust or update. Insights are not
live: they are fetched once and cached for a minute, because the analytics API is rate limited.

## Visual redesign (2026-11-15)
Landing page: dark hero with a decorative illustration of the staff board and a patient's phone (no real data, no performance
claims), a feature grid, "how a visit works", and a plain "what this is" footer. Sign-in and register use a split layout. The
signed-in app has a dark sidebar (mobile: top bar), user area and pill tabs inside a clinic. Fonts are Bricolage Grotesque and
Figtree through `next/font/google`; the dev server downloads them, so without internet it falls back to the system font
with a warning. **Status: the first landing/auth version was seen and approved by the author; the premium landing and
the sidebar shell are written, type-checked only for syntax in the sandbox, and not yet seen.** A third pass restyled the staff board (summary tiles, a dark "with the doctor" card, token
rows with the next patient highlighted), the dashboard, clinic directory, clinic overview, booking, appointments (calendar
tile) and "My queue" (ticket-style token card). Status of the second and third passes: written and checked for
syntax only; not yet seen by the author. No behaviour was changed except a new `dayOf`/`monthOf` formatter with a unit test.

## What is in this slice (F1)
| Route | Who | What |
|---|---|---|
| `/` | anyone | Landing page with honest limits |
| `/register`, `/login` | anyone | Account creation and sign-in (server enforces password rules, lockout and rate limits) |
| `/app` | signed in | Your clinics |
| `/app/clinics` | signed in | Search and browse active clinics (12 at a time); join as a patient |
| `/app/c/{id}` | patient | Next appointment and today's queue |
| `/app/c/{id}/book` | patient | Pick doctor, pick a slot (clinic time zone), book; 409 "slot taken" shows alternative doctors |
| `/app/c/{id}/appointments` | patient | List and cancel |
| `/app/c/{id}/queue` | patient | Live token, people ahead, wait estimate with its source (model or rule) |

## F2: staff screens
| Route | Who | What |
|---|---|---|
| `/app/c/{id}/board` | admin, receptionist | Every active doctor's queue (with the doctor, waiting, skipped); call next, call/start/complete/skip/requeue/no-show/remove; a panel to check in today's booked patients; a panel to add a walk-in (search a patient, or register a new one) |
| `/app/c/{id}/board` | doctor | Only their own queue, with the same clinical actions (no "remove") |

Staff are redirected to the board; patients cannot reach it. A doctor login has no "who am I" endpoint, so the page asks for
each doctor's board and keeps the one the API allows (the others answer 404). A `GET /doctors/me` endpoint would be cleaner.

**Live updates.** `src/lib/realtime.ts` opens the WebSocket documented in [realtime.md](realtime.md): it asks for a
single-use ticket, connects, pings every 30 s, ignores repeated event ids, refetches over REST on connect and on
`resync`, and reconnects with a fresh ticket and exponential back-off. Events are only "something changed" hints; the
screen refetches the boards. While the socket is not live, the boards poll every 5 s (every 60 s while live, as a safety
net) and a badge says which mode you are in. A browser WebSocket cannot go through the Next dev proxy, so in development
`NEXT_PUBLIC_WS_URL` is the API origin (`ws://localhost:8000`; only its origin is used, the path comes from the server)
and the backend's `BACKEND_CORS_ORIGINS` must include the page origin (the server refuses other `Origin`s). Behind the
production proxy leave it empty and the page's own origin is used.

## How it talks to the API
* The browser only calls its own origin at `/api/v1/*`. In development Next proxies that to the backend
  (`next.config.mjs` rewrites, `API_INTERNAL_URL`); in production Caddy will route `/api/*` to the API and everything
  else to the frontend. Consequence: session cookies are same-origin and the CSRF cookie is readable by the page.
* `src/lib/api.ts`: `fetch` with `credentials: "include"`, the CSRF header on unsafe methods, a single shared
  refresh-and-retry on 401 (never on login/register), and errors normalised to `ApiError` from the backend's
  `{"error": {...}}` body. Tokens are in HttpOnly cookies the page never sees.
* Times arrive as UTC and are always displayed in the **clinic's** time zone, not the browser's.
* Authorization is enforced by the backend. The UI hides what a role cannot do, but never relies on that.
* The patient's wait estimate is polled (15 s) and queue position every 5 s; the staff board uses WebSocket push with polling as the fallback.

## Verify it (Docker, from the repository root)
```
docker compose build frontend                                  # installs dependencies
docker compose run --rm --no-deps frontend npm run typecheck   # TypeScript
docker compose run --rm --no-deps frontend npm test            # unit tests (formatting, API helpers, redirects, realtime client, queue actions)
docker compose up -d postgres redis backend frontend
```
Then open http://localhost:3000. A full walk-through needs a clinic that a platform admin has approved and a doctor with a
schedule: run `python scripts/demo_walkthrough.py ...` once (see its docstring); it prints the clinic it created. Then register
in the browser, find that clinic under "Find a clinic", join it and book.

## Known gaps
The platform-admin screens pass their browser tests (dev stack and CI) but have not been looked at by eye (see below); the staff board has no token history; the patient pages still poll instead of using WebSocket; no password reset or email verification pages; no dark mode;
no browser E2E tests (Playwright) yet; no production image or Caddy routing for the frontend yet; not audited with an
accessibility tool.


## Clinic setup (2026-11-17)
> **Status:** `npm run typecheck` is clean and the 16 browser tests pass, including `e2e/setup.spec.ts` (department add/rename/prefix check, doctor add,
> weekly hours with an overlap refusal, time off, deactivate, the team form's real server errors, and admin-only access in the page and on the
> server). The first browser run found a real layout bug (two forms overlapping in a narrow column), now fixed. The unit tests (vitest) pass: 8 files, 46 tests,
> including the 9 in `src/lib/setup.test.ts`. Not checked: appearance on phones, and the time-off conversion for a clinic in a different zone from the browser.

A **Setup** tab appears for clinic administrators only (`/app/c/{id}/setup`), with three sections:
* **Doctors:** list (including deactivated ones), add a doctor (department, appointment length, gap, optional linked login), deactivate or
  activate, and per doctor the **weekly hours** and **time off**. Hours and time off are entered in the clinic's time zone, never the
  browser's; time off is converted to UTC with `localToUtcIso` before it is sent.
* **Departments:** add (name plus a 1-3 letter queue prefix that cannot change later) and rename.
* **Team:** list staff, add an existing account by email as receptionist, doctor or administrator, deactivate or activate. An administrator
  cannot deactivate their own row here (the API also refuses removing the last active admin).

The screens only collect input and show the API's answers; the API remains the authority (admin-only, tenant isolation, overlap and
range checks). Not built: deleting departments or doctors; creating accounts for staff (a person must register first); schedule validity
dates. Browser tests: `e2e/setup.spec.ts`.

### Editing doctors and clinic settings (2026-11-19)
> **Status: verified.** `npm run typecheck` is clean, 63 unit tests pass, and all 33 browser tests pass in the e2e job of GitHub CI run #10 (the
> first local run found one real bug, a "Saved." message erased when the form restarted after saving; it is fixed and covered by
> `e2e/setup.spec.ts`). Not checked by a person: how the two new screens look and feel.
* **Edit details** on each doctor: name, department, appointment length and gap. Only fields that changed are sent. New lengths apply to
  bookings made from then on; appointments already booked keep their time.
* **Clinic tab** (admin only): clinic name, time zone, how far ahead patients can book, minimum notice, the patient cancel/reschedule cut-off
  (staff are not limited by it), queue order and whether staff may mark a walk-in urgent. The API merges settings and records each change in
  the audit log. Changing the time zone moves existing weekly hours to the new zone (they keep their clock times), which the screen warns about.
* Helpers and rules: `src/lib/setup.ts` (`validateClinic`, `clinicChanges`, `doctorChanges`, `isValidTimeZone`); tests in `src/lib/setup.test.ts`.
  Browser tests: `e2e/setup.spec.ts` (edit and refusal, then everything is put back) and `e2e/mobile.spec.ts` (both forms fit a phone).


### Find a clinic search (2026-11-22)
> **Status: the browser tests pass (39 of 39 on the dev stack, 2026-11-22),** including 3 new ones in `e2e/search.spec.ts` and the patient
> booking test, which now finds its clinic by searching. Also passing locally: the 6 new backend tests (`tests/integration/test_tenancy_rbac.py`,
> 19 pass in that file), the 7 new unit tests (`src/lib/directory.test.ts`, 85 in all) and the typecheck. Confirmed in CI too; the page has not been looked at by eye.
* **What it does:** a search box on `/app/clinics`. Every word typed must appear in the clinic's **name or address** (the slug, e.g. `city-dental`),
  ignoring case and extra spaces. Clinics whose name starts with the first word come first, then A to Z. The list shows 12 clinics, and
  **Show more clinics** adds 12 at a time (up to 100). A line under the box says what is shown ("Showing 12 of 30 clinics matching ..."); an empty
  result offers **Clear search**. The search waits 300 ms after the last keystroke, and the old list stays on screen while the next one loads.
* **API:** `GET /api/v1/clinics?q=...&limit=&offset=` (signed in). `q` is at most 100 characters (longer: 422) and only the first 5 words count.
  `%`, `_` and `\` are searched as ordinary characters. Only ACTIVE clinics are ever returned, so waiting or suspended clinics cannot be found.
* **Not there:** searching by place, suburb or specialty. A clinic has only a name, an address-style slug and a time zone, so there is nothing
  else to search; that needs new clinic fields (a backend change). The search is a plain substring match with no index: fine for hundreds of
  clinics, and a `pg_trgm` index would be the next step at many thousands.
* **Side effects:** the e2e patient test now finds its clinic by searching (the dev database collects test clinics, so a plain list would stop
  showing it). The dashboard still loads the unfiltered directory (up to 100) to turn clinic ids into names.

### Platform administration (2026-11-20)
> **Status: browser tests pass on the dev stack and in CI (36 of 36, 2026-11-22).** That includes 3 for these screens (`e2e/platform.spec.ts` x2, one
> phone-width test in `e2e/mobile.spec.ts`). The pages have not been looked at by eye.
* **Where:** `/app/platform`, reached from a **Platform** link in the main menu that only a user with the `SUPER_ADMIN` platform role sees. Anyone
  else who types the address sees a refusal, and the API refuses their requests anyway (403).
* **Clinics tab:** filter by *Waiting for approval* (the first view), *Open*, *Suspended* or *All*, each with a count. Per clinic: **Approve**
  (no warning), **Decline** and **Suspend** (both ask first: staff and patients cannot use the clinic until it is open again, it leaves the list
  patients search, its data is kept), **Reactivate**. A clinic's status decides which buttons appear (`clinicActions`).
* **Activity tab:** the audit events with the clinic's name and time, from the latest 200 the API returns. By default only clinic changes are shown
  (registered, status changed, staff added, patient joined); a switch adds sign-ins and account events. The API returns ids only (no old/new status
  and no actor name), so the screen shows what the API gives. Showing who did it and what changed would need a backend change.
* **Limits:** the clinic list shows the 200 most recent clinics (an API limit; a note appears when it is reached). There is no search.
* The browser tests sign in the platform admin once in global setup (`e2e/.auth/platform.json`, git-ignored) and create a fresh waiting clinic
  per run through the API, so they leave one extra clinic behind in the development database each run.

## Dependencies and CI notes (2026-11-18)
* `frontend/package-lock.json` is now committed and the Dockerfiles install from it (`npm ci`). Before that, every build resolved the newest
  matching versions, and one CI run failed because the registry returned 404 for `rollup@4.68.5`. `package.json` carried a
  temporary `overrides` pin of `rollup` to `4.68.3`; it was removed on 2026-11-22 (nothing installed uses `rollup` any more).
* In CI the checkout belongs to the runner's user while the dev containers run as `node`, so the e2e and frontend jobs run
  `chmod -R a+rwX frontend` first (otherwise `next dev` and `tsc` fail with EACCES). This does not occur on Docker Desktop.

## Phone width (written 2026-11-18, not yet run)
`e2e/mobile.spec.ts` opens 14 screens at 390 x 844 (public, patient, reception, doctor, admin) and fails any page that scrolls sideways,
naming the elements that stick out, plus one test that the clinic setup form fits on a phone. It also writes a full-page screenshot of each
screen to `frontend/e2e-results/mobile/` for a person to look at. It checks layout overflow only: it cannot judge readability, tap-target
comfort or taste, and it uses Chromium's phone emulation, not a real phone or another browser engine.

### Register a clinic (2026-11-25)
> **Status: the browser tests pass (41 of 41 on the dev stack, 2026-11-25), and CI is green.** That includes 2 new ones in
> `e2e/register-clinic.spec.ts`, 14 new unit tests (`src/lib/register-clinic.test.ts`, 101 unit tests in all) and the typecheck.
> The screen has not been looked at by eye on the hosted site yet.
* **What it does:** **My clinics** has a **Register a clinic** button (`/app/register-clinic`): clinic name, web address name and time zone.
  The address is suggested from the name (accents dropped, hyphens between words) and the person's own time zone is pre-selected.
  The form checks the same rules as the API (name 2 to 200 characters; address 3 to 63 lowercase letters, digits and hyphens; a real time zone),
  and the server checks again. An address already used by another clinic is refused with a message.
* **What happens next:** the clinic starts as waiting for approval and the person becomes its clinic admin. On **My clinics** it shows its name
  and "Waiting for approval by a platform administrator" and is not a link yet (a clinic that is not open has no pages to show). The platform
  admin approves it under **Platform**; it then appears in **Find a clinic** and its card becomes a link.
* **Why a separate address name:** the web address name is how a clinic is identified in a search, and it must be unique across all clinics.
