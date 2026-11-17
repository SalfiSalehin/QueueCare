import { defineConfig, devices } from "@playwright/test";

// Browser tests run against the development stack (see docs/frontend.md, "Browser tests").
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,                       // the tests share one seeded clinic and follow one queue
  retries: 0,                       // a flaky pass would hide a real race; fix the cause instead
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e-results/report" }]],
  outputDir: "e2e-results/artifacts",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
