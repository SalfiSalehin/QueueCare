import { expect, test } from "@playwright/test";
import { request as pwRequest } from "@playwright/test";
import { authFile, BASE_URL, readSeed } from "./helpers/seed";

test.describe("each role sees only its own area", () => {
  test("a patient is turned away from the staff board", async ({ browser }) => {
    const seed = readSeed();
    const ctx = await browser.newContext({ storageState: authFile("patient") });
    try {
      const page = await ctx.newPage();
      await page.goto(`/app/c/${seed.clinicId}/board`);
      await expect(page).toHaveURL(new RegExp(`/app/c/${seed.clinicId}$`));
      await expect(page.getByRole("navigation", { name: "Clinic" }).getByRole("link", { name: "Book" })).toBeVisible();
    } finally { await ctx.close().catch(() => undefined); }
  });

  test("a receptionist has no insights or simulation lab", async ({ browser }) => {
    const seed = readSeed();
    const ctx = await browser.newContext({ storageState: authFile("reception") });
    try {
      const page = await ctx.newPage();
      await page.goto(`/app/c/${seed.clinicId}/board`);
      const nav = page.getByRole("navigation", { name: "Clinic" });
      await expect(nav.getByRole("link", { name: "Queue board" })).toBeVisible();
      await expect(nav.getByRole("link", { name: "Insights" })).toHaveCount(0);
      await page.goto(`/app/c/${seed.clinicId}/insights`);
      await expect(page).toHaveURL(new RegExp(`/app/c/${seed.clinicId}/board$`));
    } finally { await ctx.close().catch(() => undefined); }
  });

  test("the server refuses analytics to a patient and to a receptionist, not just the page", async () => {
    const seed = readSeed();
    for (const role of ["patient", "reception"] as const) {
      const api = await pwRequest.newContext({ baseURL: BASE_URL, storageState: authFile(role) });
      const res = await api.get(`/api/v1/clinics/${seed.clinicId}/analytics/overview`);
      expect(res.status(), `${role} must be forbidden`).toBe(403);
      await api.dispose();
    }
  });

  test("a clinic the user does not belong to looks like it does not exist", async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: authFile("patient") });
    try {
      const res = await ctx.request.get("/api/v1/clinics/00000000-0000-4000-8000-000000000000/doctors");
      expect(res.status()).toBe(404);
    } finally { await ctx.close().catch(() => undefined); }
  });
});

test("a clinic admin can read the insights and run the simulation lab", async ({ browser }) => {
  const seed = readSeed();
  const ctx = await browser.newContext({ storageState: authFile("admin") });
  try {
    const page = await ctx.newPage();
    await page.goto(`/app/c/${seed.clinicId}/insights`);
    await expect(page.getByRole("heading", { name: "Insights" })).toBeVisible();
    await expect(page.getByText("No-show rate")).toBeVisible();
    for (const [tab, text] of [["Doctors", "Booked use"], ["Busy times", "Arrivals by weekday"], ["Estimate quality", "Has the data changed?"], ["Slot advice", "Slot length advice"]] as const) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByText(text).first()).toBeVisible();
    }
    await expect(page.locator("main").getByRole("alert")).toHaveCount(0);   // no tab ended in an error

    await page.goto(`/app/c/${seed.clinicId}/simulation`);
    await page.getByRole("button", { name: "Add a comparison" }).click();
    await page.getByRole("button", { name: "Run simulation" }).click();
    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(table.getByRole("row")).toHaveCount(3);     // header + two scenarios
    await expect(page.getByText("not a forecast of this clinic")).toBeVisible();
  } finally { await ctx.close().catch(() => undefined); }
});
