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
    python scripts/demo_walkthrough.py --platform-email platform@example.com --showcase   # fictional names, livelier queue, for screenshots

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
    ap.add_argument("--showcase", action="store_true",
                    help="use realistic FICTIONAL names (not 'Demo ...'), more visits and a livelier queue, for screenshots and recordings")
    ap.add_argument("--insecure", action="store_true",
                    help="skip TLS verification; ONLY for https://localhost rehearsals with Caddy's local certificate")
    a = ap.parse_args()
    platform_password = os.environ.get("QUEUECARE_ADMIN_PASSWORD")
    if not platform_password:
        sys.exit("Set QUEUECARE_ADMIN_PASSWORD to the platform admin's password.")
    run = time.strftime("%m%d%H%M%S")

    # Invented names for --showcase. Any resemblance to a real person is a coincidence; the addresses are on example.com (never delivered).
    people = {"admin": ("Nadia Karim", "nadia.karim"), "reception": ("Tariq Hossain", "tariq.hossain"),
              "doctor": ("Amina Rahman", "amina.rahman"), "patient": ("Imran Chowdhury", "imran.chowdhury")}
    clinic_name = "Lakeside Family Clinic" if a.showcase else f"Demo Clinic {run}"
    doctor_name = "Dr Amina Rahman" if a.showcase else "Dr Synthetic"
    walk_ins = (["Farhana Akter", "Rahim Uddin", "Sumaiya Islam", "Kamal Hasan", "Nusrat Jahan", "Zahid Karim"] if a.showcase
                else ["Walk-in Synthetic A", "Walk-in Synthetic B", "Walk-in Synthetic C"])

    def user(role: str) -> tuple[Client, dict, str]:
        full_name, stem = people[role] if a.showcase else (f"Demo {role.title()}", f"demo-{run}-{role}")
        c, email = Client(a.base, a.origin, a.insecure), (f"{stem}.{run}@example.com" if a.showcase else f"{stem}@example.com")
        me = c.call("POST", "/auth/register", {"email": email, "password": DEMO_PASSWORD, "full_name": full_name})
        c.call("POST", "/auth/login", {"email": email, "password": DEMO_PASSWORD})
        return c, me, email

    step("1. Register four synthetic users and sign in (Argon2id passwords, cookie sessions, CSRF)")
    admin, _, admin_email = user("admin")
    recep, _, recep_email = user("reception")
    doctor, doctor_me, doctor_email = user("doctor")
    patient, _, patient_email = user("patient")

    step("2. Admin registers a clinic (PENDING) and a platform admin approves it")
    clinic = admin.call("POST", "/clinics", {"name": clinic_name, "slug": f"lakeside-{run}" if a.showcase else f"demo-{run}"})
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
    doc = admin.call("POST", f"{base}/doctors", {"display_name": doctor_name, "department_id": dept["id"],
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
    for name in walk_ins:
        p = recep.call("POST", f"{base}/patients", {"full_name": name})
        tokens.append(recep.call("POST", f"{base}/queue/walk-ins", {"doctor_id": doc["id"], "patient_id": p["id"]}))
    print("tokens issued:", ", ".join(t["token_label"] for t in tokens))
    est = recep.call("GET", f"{base}/queue/tokens/{tokens[-1]['id']}/estimate")
    print(f"estimate for the last walk-in: source={est['source']} "
          f"median={est['median_minutes']} min, range {est['lower_minutes']}-{est['upper_minutes']} "
          f"(staff view; factors listed: {len(est.get('factors') or [])})")
    done = 3 if a.showcase else 2          # showcase: three visits finished, one in progress, the rest still waiting
    for t in tokens[:done]:
        doctor.call("POST", f"{base}/queue/tokens/{t['id']}/call")
        doctor.call("POST", f"{base}/queue/tokens/{t['id']}/start")
        doctor.call("POST", f"{base}/queue/tokens/{t['id']}/complete")
    if a.showcase:
        doctor.call("POST", f"{base}/queue/tokens/{tokens[done]['id']}/call")
        doctor.call("POST", f"{base}/queue/tokens/{tokens[done]['id']}/start")
    board = doctor.call("GET", f"{base}/doctors/{doc['id']}/queue")
    print(f"{done} visits completed; board now: {json.dumps(board)[:200]}...")

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
    if a.showcase:
        print(f"\nSign in at {a.origin}/login (password for all four: {DEMO_PASSWORD}):")
        for label, em in (("clinic admin", admin_email), ("receptionist", recep_email), ("doctor", doctor_email), ("patient", patient_email)):
            print(f"  {label:13} {em}")


if __name__ == "__main__":
    main()
