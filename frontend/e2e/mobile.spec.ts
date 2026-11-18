import { expect, test, type Browser, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { authFile, readSeed, type Role } from "./helpers/seed";

// Phone-width check (390 x 844). It cannot judge taste, but it does catch the commonest phone bug: a page that
// scrolls sideways because something is wider than the screen. Full-page screenshots are written to
// e2e-results/mobile/ so a person can look at every screen the way a phone shows it.
const VIEWPORT = { width: 390, height: 844 };
const OUT = "e2e-results/mobile";

interface Screen { name: string; role: Role | null; path: (clinicId: string) => string }

const SCREENS: Screen[] = [
  { name: "landing", role: null, path: () => "/" },
  { name: "sign-in", role: null, path: () => "/login" },
  { name: "register", role: null, path: () => "/register" },
  { name: "patient-home", role: "patient", path: () => "/app" },
  { name: "patient-find-clinic", role: "patient", path: () => "/app/clinics" },
  { name: "patient-clinic", role: "patient", path: (c) => `/app/c/${c}` },
  { name: "patient-book", role: "patient", path: (c) => `/app/c/${c}/book` },
  { name: "patient-appointments", role: "patient", path: (c) => `/app/c/${c}/appointments` },
  { name: "patient-queue", role: "patient", path: (c) => `/app/c/${c}/queue` },
  { name: "reception-board", role: "reception", path: (c) => `/app/c/${c}/board` },
  { name: "doctor-board", role: "doctor", path: (c) => `/app/c/${c}/board` },
  { name: "admin-insights", role: "admin", path: (c) => `/app/c/${c}/insights` },
  { name: "admin-simulation", role: "admin", path: (c) => `/app/c/${c}/simulation` },
  { name: "admin-setup", role: "admin", path: (c) => `/app/c/${c}/setup` },
];

/** Elements that stick out past the right edge of the screen, ignoring ones inside a deliberate horizontal scroller. */
async function sidewaysOverflow(page: Page): Promise<{ extra: number; culprits: string[] }> {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const extra = document.documentElement.scrollWidth - vw;
    const inScroller = (el: Element): boolean => {
      for (let p: Element | null = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if (ox === "auto" || ox === "scroll" || ox === "hidden") return true;
      }
      return false;
    };
    const culprits = extra <= 1 ? [] : [...document.body.querySelectorAll("*")]
      .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1 && !inScroller(el); })
      .slice(0, 6)
      .map((el) => {
        const cls = typeof el.className === "string" ? el.className.split(/\s+/).filter(Boolean).slice(0, 3).join(".") : "";
        const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 30);
        return `<${el.tagName.toLowerCase()}${cls ? "." + cls : ""}> "${text}"`;
      });
    return { extra, culprits };
  });
}

async function open(browser: Browser, role: Role | null) {
  return browser.newContext({
    viewport: VIEWPORT, isMobile: true, hasTouch: true, deviceScaleFactor: 2,
    ...(role ? { storageState: authFile(role) } : {}),
  });
}

test.describe("phone width", () => {
  mkdirSync(OUT, { recursive: true });
  for (const s of SCREENS) {
    test(`${s.name} does not scroll sideways`, async ({ browser }) => {
      const seed = readSeed();
      const ctx = await open(browser, s.role);
      try {
        const page = await ctx.newPage();
        await page.goto(s.path(seed.clinicId));
        await page.locator("main, h1").first().waitFor({ timeout: 20_000 });
        await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
        await page.screenshot({ path: `${OUT}/${s.name}.png`, fullPage: true });
        const { extra, culprits } = await sidewaysOverflow(page);
        expect(extra, `${s.name} is ${extra}px wider than the screen. Sticking out: ${culprits.join(" | ") || "(could not find)"}`).toBeLessThanOrEqual(1);
      } finally { await ctx.close().catch(() => undefined); }
    });
  }

  test("the staff tabs and the clinic setup form stay usable on a phone", async ({ browser }) => {
    const seed = readSeed();
    const ctx = await open(browser, "admin");
    try {
      const page = await ctx.newPage();
      await page.goto(`/app/c/${seed.clinicId}/board`);
      const nav = page.getByRole("navigation", { name: "Clinic" });
      await expect(nav.getByRole("link", { name: "Setup" })).toBeVisible();
      await nav.getByRole("link", { name: "Setup" }).click();
      await page.getByRole("button", { name: /^Hours and time off for/ }).first().click();
      const add = page.getByRole("button", { name: "Add hours" });
      await add.scrollIntoViewIfNeeded();
      await expect(add).toBeVisible();
      const box = await add.boundingBox();
      expect(box, "Add hours must be on screen").not.toBeNull();
      expect((box?.x ?? 0) + (box?.width ?? 0), "Add hours must fit inside the screen width").toBeLessThanOrEqual(VIEWPORT.width);
      await page.screenshot({ path: `${OUT}/admin-setup-hours.png`, fullPage: true });
    } finally { await ctx.close().catch(() => undefined); }
  });
});
