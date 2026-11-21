import { expect, test } from "@playwright/test";
import { Session } from "./helpers/api";
import { authFile, platformAuthFile, readSeed } from "./helpers/seed";

// "Find a clinic": a signed-in patient searches the open clinics by name or address.
// The e2e image holds only this folder, not the app's source, so the page size is written out here. It must match PAGE_SIZE in
// src/lib/directory.ts: if the app changes it, the paging test fails and says so.
const PAGE_SIZE = 12;
test.use({ storageState: authFile("patient") });

test.describe("find a clinic", () => {
  test("a clinic is found by its name, in any case or word order, or by its address", async ({ page }) => {
    const seed = readSeed();
    await page.goto("/app/clinics");
    const box = page.getByLabel("Search clinics");
    const found = page.getByRole("heading", { name: seed.clinicName, level: 2, exact: true });
    const status = page.getByRole("status");
    const items = page.locator("main").getByRole("listitem");     // the clinic cards (not the menu's list items)

    await box.fill(`clinic ${seed.run}`);                       // lower case: the name has "Clinic"
    await expect(found).toBeVisible();
    await expect(status.filter({ hasText: `1 clinic matching "clinic ${seed.run}"` })).toBeVisible();
    await expect(items).toHaveCount(1);

    await box.fill(`${seed.run}   CLINIC `);                    // another order, capitals, extra spaces
    await expect(found).toBeVisible();
    await expect(items).toHaveCount(1);

    await box.fill(`e2e-${seed.run}`);                          // the address, not the name
    await expect(found).toBeVisible();
    await expect(items).toHaveCount(1);
  });

  test("a search with no match says so and can be cleared", async ({ page }) => {
    const seed = readSeed();
    await page.goto("/app/clinics");
    const box = page.getByLabel("Search clinics");
    const items = page.locator("main").getByRole("listitem");

    await box.fill(`zzzz-${seed.run}-nothing`);
    await expect(page.getByText("No clinic matches that search.")).toBeVisible();
    await expect(items).toHaveCount(0);

    await page.getByRole("button", { name: "Clear search" }).click();
    await expect(box).toHaveValue("");
    await expect(page.getByText("No clinic matches that search.")).toHaveCount(0);
    await expect(items.first()).toBeVisible();
  });

  test("a long list shows a page at a time and Show more adds the rest", async ({ page }) => {
    const seed = readSeed();
    const total = PAGE_SIZE + 1;
    const stem = `Paging ${seed.run}`;
    const owner = await Session.create(authFile("admin"));
    const platform = await Session.create(platformAuthFile);
    const made: string[] = [];
    try {
      for (let i = 1; i <= total; i++) {
        const n = String(i).padStart(2, "0");
        const c = await owner.call<{ id: string }>("POST", "/clinics", { name: `${stem} ${n}`, slug: `paging-${seed.run}-${n}` });
        made.push(c.id);
        await platform.call("POST", `/platform/clinics/${c.id}/status`, { status: "ACTIVE" });
      }

      await page.goto("/app/clinics");
      const items = page.locator("main").getByRole("listitem");
      await page.getByLabel("Search clinics").fill(stem);
      await expect(page.getByRole("status").filter({ hasText: `Showing ${PAGE_SIZE} of ${total} clinics matching "${stem}"` })).toBeVisible();
      await expect(items).toHaveCount(PAGE_SIZE);

      await page.getByRole("button", { name: "Show more clinics" }).click();
      await expect(items).toHaveCount(total);
      await expect(page.getByRole("status").filter({ hasText: `${total} clinics matching "${stem}"` })).toBeVisible();
      await expect(page.getByRole("button", { name: "Show more clinics" })).toHaveCount(0);

      // A new search starts again from the first page. (The run id is in these clinics' names and in the seed clinics' names, so
      // there are more than a page of matches however many other clinics exist.)
      await page.getByLabel("Search clinics").fill(seed.run);
      await expect(items).toHaveCount(PAGE_SIZE);
      await expect(page.getByRole("button", { name: "Show more clinics" })).toBeVisible();
    } finally {
      // Suspending takes them out of the directory again, so test clinics do not pile up in the development database.
      for (const id of made) await platform.call("POST", `/platform/clinics/${id}/status`, { status: "SUSPENDED" }).catch(() => undefined);
      await owner.close(); await platform.close();
    }
  });
});
