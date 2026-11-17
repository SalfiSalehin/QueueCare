import { expect, test } from "@playwright/test";
import { authFile, readSeed } from "./helpers/seed";

// One walk-in followed from the front desk, through the doctor, to the patient's own screen.
// The patient's page reacts either to the live connection or to its 5-second polling; the reception board
// shows which one is active, and the test requires the live connection there.
test("a walk-in moves from reception to the doctor and the patient sees every step", async ({ browser }) => {
  const seed = readSeed();
  const reception = await browser.newContext({ storageState: authFile("reception") });
  const doctor = await browser.newContext({ storageState: authFile("doctor") });
  const patient = await browser.newContext({ storageState: authFile("patient") });
  try {
    const patientPage = await patient.newPage();
    await patientPage.goto(`/app/c/${seed.clinicId}/queue`);
    await expect(patientPage.getByText("You are not in today's queue.")).toBeVisible();

    const desk = await reception.newPage();
    await desk.goto(`/app/c/${seed.clinicId}/board`);
    await expect(desk.getByText("Live updates on")).toBeVisible();
    await desk.getByLabel("Find a patient").fill(seed.patientName);
    await desk.getByRole("button", { name: "Add to queue", exact: true }).click();
    await expect(desk.getByText(/is in the queue as G-\d+/)).toBeVisible();

    await expect(patientPage.getByText(/^G-\d+$/).first()).toBeVisible();
    await expect(patientPage.getByText("waiting", { exact: true })).toBeVisible();

    const doc = await doctor.newPage();
    await doc.goto(`/app/c/${seed.clinicId}/board`);
    await expect(doc.getByRole("button", { name: "Remove" })).toHaveCount(0);          // doctors cannot remove tokens
    await doc.getByRole("button", { name: "Call", exact: true }).click();
    await expect(patientPage.getByText("It is your turn")).toBeVisible();

    await doc.getByRole("button", { name: "Start", exact: true }).click();
    await expect(patientPage.getByText("in consultation")).toBeVisible();

    await doc.getByRole("button", { name: "Complete", exact: true }).click();
    await expect(patientPage.getByText("completed", { exact: true })).toBeVisible();
  } finally {
    await Promise.allSettled([reception.close(), doctor.close(), patient.close()]);   // never let cleanup hide the real failure
  }
});

test("front desk can open the explanation for a waiting patient's estimate", async ({ browser }) => {
  const seed = readSeed();
  const reception = await browser.newContext({ storageState: authFile("reception") });
  try {
    const desk = await reception.newPage();
    await desk.goto(`/app/c/${seed.clinicId}/board`);
    await desk.getByLabel("Find a patient").fill(seed.patientName);
    await desk.getByRole("button", { name: "Add to queue", exact: true }).click();
    await expect(desk.getByText(/is in the queue as G-\d+/)).toBeVisible();
    await desk.getByRole("button", { name: "Wait estimate" }).click();
    await expect(desk.getByText(/About \d+ min/)).toBeVisible();
    await expect(desk.getByText(/simple rule|trained on simulated data/)).toBeVisible();
  } finally {
    await reception.close().catch(() => undefined);
  }
});
