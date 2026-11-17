import { expect, test } from "@playwright/test";

test.describe("signed out", () => {
  test("the landing page explains the product and leads to sign-up", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Know where you stand in line");
    await expect(page.getByText("Demonstration system: synthetic data only")).toBeVisible();
    await page.getByRole("link", { name: "Create an account" }).first().click();
    await expect(page).toHaveURL(/\/register$/);
    await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  });

  test("a protected page sends you to sign in", async ({ page }) => {
    await page.goto("/app/clinics");
    await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fclinics/);
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  });

  test("a wrong password gives one generic message and stays on the page", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("nobody@example.com");
    await page.getByLabel("Password").fill("not-the-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator("main").getByRole("alert")).toContainText("Invalid email or password.");
    await expect(page).toHaveURL(/\/login/);
  });

  test("the sign-up form checks the password before calling the server", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Full name").fill("Short Password");
    await page.getByLabel("Email").fill("short@example.com");
    await page.getByLabel("Password").fill("short");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.locator("main").getByRole("alert").first()).toBeVisible();
    await expect(page).toHaveURL(/\/register$/);
  });

  test("the API refuses anonymous requests", async ({ request }) => {
    const res = await request.get("/api/v1/auth/me");
    expect(res.status()).toBe(401);
    expect((await res.json()).error.code).toBe("unauthorized");
  });
});
