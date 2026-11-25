import { expect, test, type Browser } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { Session } from "./helpers/api";
import { PASSWORD, platformAuthFile, readSeed } from "./helpers/seed";

// "Register a clinic": a signed-in person registers a clinic from the dashboard, it waits for approval, and the platform
// administrator opens it. The person is a new account (not a clinic member yet), made through the API like a sign-up would.
// One account serves both tests, so the suite adds a single sign-up toward the hourly sign-up limit.
test.describe.configure({ mode: "serial" });

let dir = "";
let ownerState = "";

test.beforeAll(async () => {
  const seed = readSeed();
  dir = mkdtempSync(path.join(os.tmpdir(), "qc-register-"));
  ownerState = path.join(dir, "owner.json");
  const email = `e2e-${seed.run}-registrant@example.com`;
  const api = await Session.create();
  try {
    await api.call("POST", "/auth/register", { email, password: PASSWORD, full_name: `E2E Registrant ${seed.run}` });
    await api.call("POST", "/auth/login", { email, password: PASSWORD });
    await api.saveState(ownerState);
  } finally { await api.close(); }
});

test.afterAll(() => { if (dir) rmSync(dir, { recursive: true, force: true }); });

const ownerPage = async (browser: Browser) => {
  const ctx = await browser.newContext({ storageState: ownerState });
  return { ctx, page: await ctx.newPage() };
};

test.describe("register a clinic", () => {
  test("a clinic is registered, waits for approval, and opens once a platform admin approves it", async ({ browser }) => {
    const seed = readSeed();
    const name = `E2E Register ${seed.run}`;
    const expectedAddress = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const { ctx, page } = await ownerPage(browser);
    const platform = await Session.create(platformAuthFile);
    let clinicId: string | undefined;
    try {
      await page.goto("/app");
      await page.getByRole("link", { name: "Register a clinic" }).click();
      await expect(page.getByRole("heading", { name: "Register a clinic", level: 1 })).toBeVisible();

      // The address is suggested from the name, and the person's own time zone is already chosen.
      await page.getByLabel("Clinic name", { exact: true }).fill(name);
      await expect(page.getByLabel("Clinic web address name")).toHaveValue(expectedAddress);
      await expect(page.getByLabel("Time zone")).not.toHaveValue("");
      await page.getByRole("button", { name: "Register clinic" }).click();
      await expect(page.getByText("has been submitted")).toBeVisible();

      // It is listed for its owner, marked as waiting, and is not a link yet: there is nothing to open.
      await page.getByRole("link", { name: "Go to My clinics" }).click();
      const main = page.locator("main");
      await expect(main.getByText(name, { exact: true })).toBeVisible();
      await expect(main.getByText("Waiting for approval by a platform administrator")).toBeVisible();
      await expect(main.getByRole("link", { name: new RegExp(name) })).toHaveCount(0);

      // The platform administrator sees it among the clinics waiting, and approves it.
      const adminCtx = await browser.newContext({ storageState: platformAuthFile });
      try {
        const admin = await adminCtx.newPage();
        await admin.goto("/app/platform");
        await expect(admin.locator("main").getByRole("heading", { name, exact: true })).toBeVisible();
        await admin.getByRole("button", { name: `Approve ${name}` }).click();
        await expect(admin.locator("main").getByRole("heading", { name, exact: true })).toHaveCount(0);
      } finally { await adminCtx.close().catch(() => undefined); }

      // Now the owner's card is a link to the clinic and the waiting note is gone.
      await page.reload();
      const link = page.locator("main").getByRole("link", { name: new RegExp(name) });
      await expect(link).toBeVisible();
      await expect(page.locator("main").getByText("Waiting for approval")).toHaveCount(0);
      clinicId = (await link.getAttribute("href"))?.split("/").pop();
    } finally {
      // Suspending takes it out of the directory again, so test clinics do not pile up in the development database.
      if (clinicId) await platform.call("POST", `/platform/clinics/${clinicId}/status`, { status: "SUSPENDED" }).catch(() => undefined);
      await platform.close();
      await ctx.close().catch(() => undefined);
    }
  });

  test("the form says what is wrong, and an address that is already used is refused", async ({ browser }) => {
    const seed = readSeed();
    const { ctx, page } = await ownerPage(browser);
    try {
      await page.goto("/app/register-clinic");
      await page.getByRole("button", { name: "Register clinic" }).click();
      await expect(page.getByText("Enter the clinic's name")).toBeVisible();
      await expect(page.getByText("Use at least 3 characters.")).toBeVisible();

      await page.getByLabel("Clinic name", { exact: true }).fill("Another Clinic");
      await page.getByLabel("Clinic web address name").fill("Bad Address!");
      await page.getByRole("button", { name: "Register clinic" }).click();
      await expect(page.getByText(/Use lowercase letters, digits and hyphens only/)).toBeVisible();

      await page.getByLabel("Time zone").fill("Mars/Olympus");
      await page.getByLabel("Clinic web address name").fill("fine-address");
      await page.getByRole("button", { name: "Register clinic" }).click();
      await expect(page.getByText(/Choose a time zone from the list/)).toBeVisible();

      // The seed clinic already owns this address, so the server refuses it and the person is told why.
      await page.getByLabel("Time zone").fill("UTC");
      await page.getByLabel("Clinic web address name").fill(`e2e-${seed.run}`);
      await page.getByRole("button", { name: "Register clinic" }).click();
      await expect(page.getByRole("alert").filter({ hasText: "That clinic address is already taken." })).toBeVisible();
      await expect(page.getByText("has been submitted")).toHaveCount(0);
    } finally { await ctx.close().catch(() => undefined); }
  });
});
