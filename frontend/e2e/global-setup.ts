import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { Session } from "./helpers/api";
import { startForward } from "./helpers/forward";
import { authFile, BASE_URL, PASSWORD, seedFile, type Role, type Seed } from "./helpers/seed";

interface Created { id: string }

/**
 * Builds one synthetic clinic through the real API (the same calls the app makes): four users, a clinic approved by a
 * platform admin, staff, a doctor linked to the doctor's login with a weekly schedule, and a patient who joined.
 * Then saves each user's signed-in cookies so tests do not spend login attempts (login is rate limited).
 *
 * Needs a platform admin account (see docs/frontend.md): E2E_PLATFORM_EMAIL and QUEUECARE_ADMIN_PASSWORD.
 * Registration is limited to 10 per hour per address and each run registers 5 (4 here + 1 in a test).
 */
export default async function globalSetup(): Promise<() => Promise<void>> {
  const platformEmail = process.env.E2E_PLATFORM_EMAIL;
  const platformPassword = process.env.E2E_PLATFORM_PASSWORD ?? process.env.QUEUECARE_ADMIN_PASSWORD;
  if (!platformEmail || !platformPassword) {
    throw new Error("Set E2E_PLATFORM_EMAIL and QUEUECARE_ADMIN_PASSWORD (the platform admin created with `python -m app.cli create-superadmin`).");
  }

  const stopForward = await startForward(8000, process.env.E2E_BACKEND_HOST ?? "backend", 8000);
  const run = Date.now().toString(36);
  const emails: Record<Role, string> = {
    admin: `e2e-${run}-admin@example.com`, reception: `e2e-${run}-reception@example.com`,
    doctor: `e2e-${run}-doctor@example.com`, patient: `e2e-${run}-patient@example.com`,
  };
  const names: Record<Role, string> = {
    admin: `E2E Admin ${run}`, reception: `E2E Reception ${run}`, doctor: `E2E Doctor ${run}`, patient: `E2E Patient ${run}`,
  };
  mkdirSync(path.dirname(authFile("admin")), { recursive: true });

  const sessions = {} as Record<Role, Session>;
  const ids = {} as Record<Role, string>;
  for (const role of ["admin", "reception", "doctor", "patient"] as const) {
    const s = await Session.create();
    const me = await s.call<Created>("POST", "/auth/register", { email: emails[role], password: PASSWORD, full_name: names[role] });
    await s.call("POST", "/auth/login", { email: emails[role], password: PASSWORD });
    sessions[role] = s; ids[role] = me.id;
  }

  const clinicName = `E2E Clinic ${run}`;
  const clinic = await sessions.admin.call<Created>("POST", "/clinics", { name: clinicName, slug: `e2e-${run}` });
  const root = await Session.create();
  await root.call("POST", "/auth/login", { email: platformEmail, password: platformPassword });
  await root.call("POST", `/platform/clinics/${clinic.id}/status`, { status: "ACTIVE" });
  await root.close();

  const base = `/clinics/${clinic.id}`;
  await sessions.admin.call("POST", `${base}/members`, { email: emails.reception, role: "RECEPTIONIST" });
  await sessions.admin.call("POST", `${base}/members`, { email: emails.doctor, role: "DOCTOR" });
  await sessions.patient.call("POST", `${base}/join`);
  const dept = await sessions.admin.call<Created>("POST", `${base}/departments`, { name: "General Medicine", queue_prefix: "G" });
  const doctor = await sessions.admin.call<Created>("POST", `${base}/doctors`, {
    display_name: "Dr Synthetic", department_id: dept.id, default_slot_minutes: 30, buffer_minutes: 0, user_id: ids.doctor,
  });
  for (let dow = 0; dow < 7; dow++) {
    await sessions.admin.call("POST", `${base}/doctors/${doctor.id}/schedules`, { day_of_week: dow, start_time: "09:00:00", end_time: "17:00:00" });
  }
  // Lets the booking test cancel its appointment (patients cannot cancel inside the cutoff window).
  await sessions.admin.call("PATCH", base, { settings: { cancellation_cutoff_hours: 0 } });

  // No booking is needed here: joining the clinic creates the patient profile, so reception can find this person
  // for a walk-in. (Before that fix the seed had to book once; the queue tests now prove the join does the job.)

  for (const role of ["admin", "reception", "doctor", "patient"] as const) {
    await sessions[role].saveState(authFile(role));
    await sessions[role].close();
  }
  await warmUp(clinic.id);
  const seed: Seed = { run, clinicId: clinic.id, clinicName, doctorId: doctor.id, patientName: names.patient, emails };
  writeFileSync(seedFile, JSON.stringify(seed, null, 2));
  return stopForward;
}

/**
 * Loads the main pages once in a real browser, signed in, so the development server compiles them and the API warms up
 * BEFORE the first test starts the clock. Without this the first test (after a restart) can miss its 15 s wait. Best
 * effort: a failure here never fails the run, the tests simply carry the cold-start cost as before.
 */
async function warmUp(clinicId: string): Promise<void> {
  const base = `/app/c/${clinicId}`;
  const visits: [Role, string[]][] = [
    ["patient", [`${base}/board`, `${base}/book`, `${base}/appointments`, `${base}/queue`]],
    ["admin", [`${base}/board`, `${base}/insights`, `${base}/simulation`, `${base}/setup`]],
  ];
  const browser = await chromium.launch().catch(() => null);
  if (!browser) return;
  try {
    for (const [role, routes] of visits) {
      const ctx = await browser.newContext({ storageState: authFile(role), baseURL: BASE_URL });
      const page = await ctx.newPage();
      for (const route of routes) {
        await page.goto(route, { timeout: 60_000, waitUntil: "load" }).catch(() => undefined);
        await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
      }
      await ctx.close().catch(() => undefined);
    }
  } finally {
    await browser.close().catch(() => undefined);
  }
}
