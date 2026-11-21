import { expect, request as pwRequest, test } from "@playwright/test";
import { Session } from "./helpers/api";
import { authFile, BASE_URL, PASSWORD, platformAuthFile, readSeed } from "./helpers/seed";

// The platform administrator approves, suspends and reopens clinics. A new clinic is created through the API
// (as a clinic owner would), so it starts out waiting for approval.
test.describe("platform administration", () => {
  test("a platform admin approves, suspends and reopens a clinic, and the activity log records each step", async ({ browser }) => {
    const seed = readSeed();
    const name = `E2E Pending ${seed.run}`;
    const owner = await Session.create();
    try {
      const email = `e2e-${seed.run}-pending@example.com`;
      await owner.call("POST", "/auth/register", { email, password: PASSWORD, full_name: `E2E Owner ${seed.run}` });
      await owner.call("POST", "/auth/login", { email, password: PASSWORD });
      await owner.call("POST", "/clinics", { name, slug: `e2e-pending-${seed.run}` });
    } finally { await owner.close(); }

    const ctx = await browser.newContext({ storageState: platformAuthFile });
    try {
      const page = await ctx.newPage();
      await page.goto("/app/platform");
      const main = page.locator("main");
      const card = main.getByRole("heading", { name, exact: true });
      await expect(main.getByRole("heading", { name: "Platform", level: 1 })).toBeVisible();

      // Waiting for approval is the first view. Approving needs no warning and moves the clinic to Open.
      await expect(card).toBeVisible();
      await page.getByRole("button", { name: `Approve ${name}` }).click();
      await expect(card).toHaveCount(0);
      await page.getByRole("tab", { name: /^Open \(/ }).click();
      await expect(card).toBeVisible();

      // Suspending locks people out, so it asks first; cancelling changes nothing.
      await page.getByRole("button", { name: `Suspend ${name}` }).click();
      await expect(main.getByText(/cannot use it until it is open again/)).toBeVisible();
      await page.getByRole("button", { name: "Cancel" }).click();
      await expect(card).toBeVisible();
      await page.getByRole("button", { name: `Suspend ${name}` }).click();
      await page.getByRole("button", { name: `Confirm Suspend ${name}` }).click();
      await expect(card).toHaveCount(0);
      await page.getByRole("tab", { name: /^Suspended \(/ }).click();
      await expect(card).toBeVisible();

      // Reopening is immediate.
      await page.getByRole("button", { name: `Reactivate ${name}` }).click();
      await expect(card).toHaveCount(0);
      await page.getByRole("tab", { name: /^Open \(/ }).click();
      await expect(card).toBeVisible();

      // The activity log shows the clinic's whole story: it was registered, then approved, suspended and reopened.
      await page.getByRole("tab", { name: "Activity" }).click();
      const rows = main.locator("li", { hasText: name });
      await expect(rows).toHaveCount(4);
      await expect(rows.filter({ hasText: "Clinic registered" })).toHaveCount(1);
      await expect(rows.filter({ hasText: "Clinic status changed" })).toHaveCount(3);
      // Sign-ins are hidden until asked for.
      await expect(main.getByText("Signed in")).toHaveCount(0);
      await page.getByLabel("Include sign-ins and account events").check();
      await expect(main.getByText("Signed in").first()).toBeVisible();
    } finally { await ctx.close().catch(() => undefined); }
  });

  test("only a platform admin sees the Platform link, the page, or the data, in the page and on the server", async ({ browser }) => {
    const admin = await browser.newContext({ storageState: authFile("admin") });
    try {
      const page = await admin.newPage();
      await page.goto("/app");
      await expect(page.getByRole("link", { name: "My clinics" }).first()).toBeVisible();
      await expect(page.getByRole("link", { name: "Platform" })).toHaveCount(0);
      await page.goto("/app/platform");
      await expect(page.getByText("Only platform administrators can open this page.")).toBeVisible();
    } finally { await admin.close().catch(() => undefined); }

    const platform = await browser.newContext({ storageState: platformAuthFile });
    try {
      const page = await platform.newPage();
      await page.goto("/app");
      await expect(page.getByRole("link", { name: "Platform" }).first()).toBeVisible();
    } finally { await platform.close().catch(() => undefined); }

    for (const role of ["admin", "reception", "doctor", "patient"] as const) {
      const api = await pwRequest.newContext({ baseURL: BASE_URL, storageState: authFile(role) });
      for (const path of ["/api/v1/platform/clinics", "/api/v1/platform/audit-logs"]) {
        expect((await api.get(path)).status(), `${role} must not read ${path}`).toBe(403);
      }
      await api.dispose();
    }
    const anonymous = await pwRequest.newContext({ baseURL: BASE_URL });
    expect((await anonymous.get("/api/v1/platform/clinics")).status()).toBe(401);
    await anonymous.dispose();
  });
});
