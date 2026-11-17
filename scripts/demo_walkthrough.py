"""End-to-end demo of QueueCare through its real HTTP API. SYNTHETIC data only; standard library only.

There is no frontend yet, so this script is the demo: it creates a clinic, staff, a doctor and a patient, books an
appointment, runs a live queue (walk-ins -> call -> start -> complete), then prints the estimate, analytics and a
simulation. Everything is created through the same endpoints a UI would call, so authorization, CSRF and row-level
security are all exercised. Safe to re-run: every run uses a fresh suffix.

Prerequisites (development stack, see docs/setup.md):
    docker compose up -d postgres redis backend
    docker compose run --rm backend alembic upgrade head
    docker compose run --rm -e QUEUECARE_ADMIN_PASSWORD="<a strong password>" backend \\
        python -m app.cli create-superadmin --email platform@example.com

Run (PowerShell):
    $env:QUEUECARE_ADMIN_PASSWORD = "<the same password>"
    python scripts/demo_walkthrough.py --platform-email platform@example.com

Rate limit: registration allows 10 per hour per IP and each run registers 4 users, so run it at most twice an hour
(a 429 from /auth/register means wait, not a bug; the limit is a deliberate security control).

The platform account is needed once per run: clinics start PENDING and a platform admin must approve them.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

DEMO_PASSWORD = "Demo-Clinic-Passw0rd!2026"   # synthetic accounts only; never reuse a real password


class Client:
    """A browser-like session: keeps cookies and echoes the CSRF cookie in the X-CSRF-Token header."""

    def __init__(self, base: str, origin: str, insecure: bool = False) -> None:
        self.base, self.origin = base.rstrip("/"), origin
        self.jar = http.cookiejar.CookieJar()
        handlers: list = [urllib.request.HTTPCookieProcessor(self.jar)]
        if insecure:  # local rehearsal only: Caddy's local CA is not trusted by Python
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*handlers)

    def call(self, method: str, path: str, body: dict | None = None, ok: tuple[int, ...] = (200, 201, 204)):
        url = f"{self.base}/api/v1{path}"
        if not url.startswith(("http://", "https://")):
            raise SystemExit("--base must start with http:// or https://")
        headers = {"Origin": self.origin}
        csrf = next((c.value for c in self.jar if c.name == "qc_csrf"), None)
        if csrf:
            headers["X-CSRF-Token"] = csrf
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 - scheme checked above
        try:
            with self.opener.open(req, timeout=30) as r:  # noqa: S310
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        parsed = json.loads(raw) if raw else None
        if status not in ok:
            raise SystemExit(f"\nFAILED {method} {path} -> {status}\n{json.dumps(parsed, indent=2)}")
        return parsed


def step(text: str) -> None:
    print(f"\n== {text}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--origin", default="http://localhost:3000", help="must be listed in BACKEND_CORS_ORIGINS")
    ap.add_argument("--platform-email", required=True)
    ap.add_argument("--insecure", action="store_true",
                    help="skip TLS verification; ONLY for https://localhost rehearsals with Caddy's local certificate")
    a = ap.parse_args()
    platform_password = os.environ.get("QUEUECARE_ADMIN_PASSWORD")
    if not platform_password:
        sys.exit("Set QUEUECARE_ADMIN_PASSWORD to the platform admin's password.")
    run = time.strftime("%m%d%H%M%S")

    def user(role: str) -> tuple[Client, dict, str]:
        c, email = Client(a.base, a.origin, a.insecure), f"demo-{run}-{role}@example.com"
        me = c.call("POST", "/auth/register", {"email": email, "password": DEMO_PASSWORD, "full_name": f"Demo {role.title()}"})
        c.call("POST", "/auth/login", {"email": email, "password": DEMO_PASSWORD})
        return c, me, email

    step("1. Register four synthetic users and sign in (Argon2id passwords, cookie sessions, CSRF)")
    admin, _, _ = user("admin")
    recep, _, recep_email = user("reception")
    doctor, doctor_me, doctor_email = user("doctor")
    patient, _, _ = user("patient")

    step("2. Admin registers a clinic (PENDING) and a platform admin approves it")
    clinic = admin.call("POST", "/clinics", {"name": f"Demo Clinic {run}", "slug": f"demo-{run}"})
    cid = clinic["id"]
    print(f"clinic {clinic['slug']} status={clinic['status']}")
    root = Client(a.base, a.origin, a.insecure)
    root.call("POST", "/auth/login", {"email": a.platform_email, "password": platform_password})
    approved = root.call("POST", f"/platform/clinics/{cid}/status", {"status": "ACTIVE"})
    print(f"status -> {approved['status']}")
    base = f"/clinics/{cid}"

    step("3. Admin adds staff; the patient joins")
    admin.call("POST", f"{base}/members", {"email": recep_email, "role": "RECEPTIONIST"})
    admin.call("POST", f"{base}/members", {"email": doctor_email, "role": "DOCTOR"})
    patient.call("POST", f"{base}/join")

    step("4. Department, doctor profile linked to the doctor's login, weekly schedule")
    dept = admin.call("POST", f"{base}/departments", {"name": "General Medicine", "queue_prefix": "G"})
    doc = admin.call("POST", f"{base}/doctors", {"display_name": "Dr Synthetic", "department_id": dept["id"],
                                                  "default_slot_minutes": 30, "buffer_minutes": 0,
                                                  "user_id": doctor_me["id"]})
    for dow in range(7):
        admin.call("POST", f"{base}/doctors/{doc['id']}/schedules",
                   {"day_of_week": dow, "start_time": "09:00:00", "end_time": "17:00:00"})
    admin.call("PATCH", base, {"settings": {"cancellation_cutoff_hours": 0}})

    step("5. Patient books the first free slot (a GiST exclusion constraint makes double booking impossible)")
    slots = patient.call("GET", f"{base}/doctors/{doc['id']}/slots")
    appt = patient.call("POST", f"{base}/appointments", {"doctor_id": doc["id"], "starts_at": slots[0]["starts_at"]})
    print(f"appointment {appt['status']} at {appt['starts_at']}")
    alt = patient.call("GET", f"{base}/doctors/{doc['id']}/alternatives")
    print(f"alternative doctors with slots: {len(alt['alternatives'])}")

    step("6. Reception registers walk-ins; the doctor runs the live queue")
    tokens = []
    for name in ("Walk-in Synthetic A", "Walk-in Synthetic B", "Walk-in Synthetic C"):
        p = recep.call("POST", f"{base}/patients", {"full_name": name})
        tokens.append(recep.call("POST", f"{base}/queue/walk-ins", {"doctor_id": doc["id"], "patient_id": p["id"]}))
    print("tokens issued:", ", ".join(t["token_label"] for t in tokens))
    est = recep.call("GET", f"{base}/queue/tokens/{tokens[-1]['id']}/estimate")
    print(f"estimate for the last walk-in: source={est['source']} "
          f"median={est['median_minutes']} min, range {est['lower_minutes']}-{est['upper_minutes']} "
          f"(staff view; factors listed: {len(est.get('factors') or [])})")
    for t in tokens[:2]:
        doctor.call("POST", f"{base}/queue/tokens/{t['id']}/call")
        doctor.call("POST", f"{base}/queue/tokens/{t['id']}/start")
        doctor.call("POST", f"{base}/queue/tokens/{t['id']}/complete")
    board = doctor.call("GET", f"{base}/doctors/{doc['id']}/queue")
    print(f"two visits completed; board now: {json.dumps(board)[:200]}...")

    step("7. Admin-only analytics, drift and scheduling advice")
    ov = admin.call("GET", f"{base}/analytics/overview")
    print("overview:", json.dumps(ov)[:300])
    print("drift status:", admin.call("GET", f"{base}/analytics/drift")["status"])
    print("slot advice:", [i["status"] for i in admin.call("GET", f"{base}/analytics/scheduling-suggestions")["items"]])

    step("8. Simulation lab (synthetic simulator; a what-if, not a forecast)")
    sim = admin.call("POST", f"{base}/simulation", {"scenarios": [
        {"name": "Baseline", "days": 10, "seed": 1},
        {"name": "Busier walk-ins", "days": 10, "seed": 1, "walk_in_per_hour": 3}]})
    for r in sim["results"]:
        print(f"{r['scenario']['name']:16} mean wait {r['outcome']['mean_wait_minutes']:.1f} min "
              f"(change vs first: {r['mean_wait_change_minutes']})")

    step("9. Isolation check: the patient cannot see admin data")
    code = patient.call("GET", f"{base}/analytics/overview", ok=(403,))
    print("patient -> analytics: 403 as expected:", code["error"]["code"])
    print(f"\nDone. Clinic id {cid}. Everything above is synthetic.")


if __name__ == "__main__":
    main()
