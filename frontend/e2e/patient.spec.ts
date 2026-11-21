import { expect, test } from "@playwright/test";
import { PASSWORD, readSeed } from "./helpers/seed";

// A brand-new person, through the real pages: register, join the clinic, book, cancel.
test.use({ storageState: { cookies: [], origins: [] } });

test("a new patient registers, joins a clinic, books a time and cancels it", async ({ page }) => {
  const seed = readSeed();
  const clinicNav = page.getByRole("navigation", { name: "Clinic" });

  await page.goto("/register");
  await page.getByLabel("Full name").fill(`E2E Walkthrough ${seed.run}`);
  await page.getByLabel("Email").fill(`e2e-ui-${seed.run}@example.com`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: "Find a clinic" })).toBeVisible();
  // The directory is searched, not scrolled: other runs leave clinics behind, so ask for this one by name.
  await page.getByLabel("Search clinics").fill(seed.clinicName);
  const card = page.getByRole("listitem").filter({ hasText: seed.clinicName });
  await card.getByRole("button", { name: "Join as a patient" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/c/${seed.clinicId}$`));

  await clinicNav.getByRole("link", { name: "Book" }).click();
  await page.getByRole("button", { name: /Dr Synthetic/ }).click();
  const slots = page.locator('section[aria-labelledby="slot-h"] button');
  await expect(slots.first()).toBeVisible();
  await slots.last().click();                         // the furthest-away time: always outside any cancellation window
  await page.getByRole("button", { name: "Book this time" }).click();

  await expect(page).toHaveURL(/\/appointments$/);
  await expect(page.getByText("confirmed")).toBeVisible();

  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Yes, cancel" }).click();
  await expect(page.getByText("cancelled")).toBeVisible();

  await clinicNav.getByRole("link", { name: "My queue" }).click();
  await expect(page.getByText("You are not in today's queue.")).toBeVisible();
});

test("a patient can sign out and is then locked out of the app", async ({ page }) => {
  const seed = readSeed();
  await page.goto("/login");
  await page.getByLabel("Email").fill(seed.emails.patient);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/app/);
  await page.getByRole("button", { name: "Sign out" }).first().click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login/);
});
