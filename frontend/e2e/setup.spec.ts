import { expect, request as pwRequest, test } from "@playwright/test";
import { authFile, BASE_URL, readSeed } from "./helpers/seed";

const DASH = "–";

test.describe("clinic setup", () => {
  test("an admin sets up a department, a doctor, hours and time off, and the team form reports real errors", async ({ browser }) => {
    const seed = readSeed();
    const ctx = await browser.newContext({ storageState: authFile("admin") });
    try {
      const page = await ctx.newPage();
      await page.goto(`/app/c/${seed.clinicId}/board`);
      await page.getByRole("navigation", { name: "Clinic" }).getByRole("link", { name: "Setup" }).click();
      await expect(page).toHaveURL(new RegExp(`/app/c/${seed.clinicId}/setup$`));
      const main = page.locator("main");

      // Departments: add, then rename.
      await page.getByRole("tab", { name: "Departments" }).click();
      await page.getByLabel("Department name").fill("Pediatrics");
      await page.getByLabel("Queue prefix").fill("p");
      await page.getByRole("button", { name: "Add department" }).click();
      await expect(main.getByText("Pediatrics was added.")).toBeVisible();
      await page.getByRole("button", { name: "Rename Pediatrics" }).click();
      await page.getByLabel("New name").fill("Paediatrics");
      await page.getByRole("button", { name: "Save name" }).click();
      await expect(main.getByText("Paediatrics", { exact: true })).toBeVisible();

      // A bad prefix is caught before the server is called.
      await page.getByLabel("Department name").fill("Dental");
      await page.getByLabel("Queue prefix").fill("12");
      await page.getByRole("button", { name: "Add department" }).click();
      await expect(main.getByText("The queue prefix is 1 to 3 letters")).toBeVisible();

      // Doctors: add one (named to sort after the seeded doctor so the queue tests are unaffected).
      await page.getByRole("tab", { name: "Doctors" }).click();
      await page.getByLabel("Doctor name").fill("Dr Zz Setup");
      await page.getByLabel("Department", { exact: true }).selectOption({ label: "Paediatrics" });
      await page.getByRole("button", { name: "Add doctor" }).click();
      await expect(main.getByText("Dr Zz Setup was added.")).toBeVisible();
      await expect(main.getByText("Dr Zz Setup", { exact: true })).toBeVisible();

      // Weekly hours: add, reject an overlap on the same day, remove.
      await page.getByRole("button", { name: "Hours and time off for Dr Zz Setup" }).click();
      await page.getByRole("button", { name: "Add hours" }).click();
      await expect(page.getByRole("button", { name: `Remove Monday 09:00${DASH}17:00` })).toBeVisible();
      await page.getByLabel("From", { exact: true }).fill("10:00");
      await page.getByLabel("To", { exact: true }).fill("11:00");
      await page.getByRole("button", { name: "Add hours" }).click();
      await expect(main.getByText(`That overlaps Monday 09:00${DASH}17:00.`)).toBeVisible();
      await page.getByRole("button", { name: `Remove Monday 09:00${DASH}17:00` }).click();
      await expect(page.getByRole("button", { name: `Remove Monday 09:00${DASH}17:00` })).toHaveCount(0);

      // Time off: add and remove.
      await page.getByLabel("Away from").fill("2030-01-10T09:00");
      await page.getByLabel("Back at").fill("2030-01-12T17:00");
      await page.getByLabel("Reason (optional)").fill("Synthetic conference");
      await page.getByRole("button", { name: "Add time off" }).click();
      await expect(main.getByText("Synthetic conference")).toBeVisible();
      await page.getByRole("button", { name: /^Remove time off starting/ }).click();
      await expect(main.getByText("Synthetic conference")).toHaveCount(0);

      // Deactivate the doctor again so nothing is left behind on the board.
      await page.getByRole("button", { name: "Deactivate Dr Zz Setup" }).click();
      await expect(main.getByText("not accepting bookings")).toBeVisible();

      // Team: the form shows the server's real reason.
      await page.getByRole("tab", { name: "Team" }).click();
      await page.getByLabel("Their email").fill(`nobody-${seed.run}@example.com`);
      await page.getByRole("button", { name: "Add to team" }).click();
      await expect(main.getByText("No active user with that email.")).toBeVisible();
      await page.getByLabel("Their email").fill(seed.emails.reception);
      await page.getByLabel("Role").selectOption("RECEPTIONIST");
      await page.getByRole("button", { name: "Add to team" }).click();
      await expect(main.getByText("User already has that role in this clinic.")).toBeVisible();
      // An admin cannot lock themselves out from this screen.
      await expect(page.getByRole("button", { name: /^Deactivate .* as clinic administrator$/ })).toBeDisabled();
    } finally { await ctx.close().catch(() => undefined); }
  });

  test("only a clinic admin gets the setup screens, in the page and on the server", async ({ browser }) => {
    const seed = readSeed();
    const ctx = await browser.newContext({ storageState: authFile("reception") });
    try {
      const page = await ctx.newPage();
      await page.goto(`/app/c/${seed.clinicId}/board`);
      await expect(page.getByRole("navigation", { name: "Clinic" }).getByRole("link", { name: "Setup" })).toHaveCount(0);
      await page.goto(`/app/c/${seed.clinicId}/setup`);
      await expect(page).toHaveURL(new RegExp(`/app/c/${seed.clinicId}/board$`));
    } finally { await ctx.close().catch(() => undefined); }
    for (const role of ["reception", "patient"] as const) {
      const api = await pwRequest.newContext({ baseURL: BASE_URL, storageState: authFile(role) });
      const res = await api.get(`/api/v1/clinics/${seed.clinicId}/members`);
      expect(res.status(), `${role} must not list the team`).toBe(403);
      await api.dispose();
    }
  });
});
