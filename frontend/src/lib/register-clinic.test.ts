import { describe, expect, it } from "vitest";
import {
  clinicStatusNote, defaultTimeZone, registrationBody, slugFromName, SLUG_MAX, validateRegistration,
} from "./register-clinic";

const good = { name: "Lakeside Family Clinic", slug: "lakeside-family-clinic", timezone: "Asia/Dhaka" };

describe("slugFromName", () => {
  it("makes a lower-case, hyphenated address", () => {
    expect(slugFromName("Lakeside Family Clinic")).toBe("lakeside-family-clinic");
    expect(slugFromName("  Dr. Rahman & Sons -- Clinic!  ")).toBe("dr-rahman-sons-clinic");
  });
  it("drops accents and keeps digits", () => {
    expect(slugFromName("Café Müller 24h")).toBe("cafe-muller-24h");
  });
  it("gives an empty address when no Latin letter or digit is left", () => {
    expect(slugFromName("ধানমন্ডি")).toBe("");
    expect(slugFromName("!!!")).toBe("");
  });
  it("never ends in a hyphen, even when cut at the length limit", () => {
    const long = `${"a".repeat(SLUG_MAX - 1)} b`;
    const slug = slugFromName(long);
    expect(slug.length).toBeLessThanOrEqual(SLUG_MAX);
    expect(slug.endsWith("-")).toBe(false);
    expect(slug).toBe("a".repeat(SLUG_MAX - 1));
  });
  it("produces an address the API pattern accepts", () => {
    expect(validateRegistration({ ...good, slug: slugFromName("Lakeside Family Clinic") })).toEqual({});
  });
});

describe("validateRegistration", () => {
  it("accepts a good form", () => {
    expect(validateRegistration(good)).toEqual({});
  });
  it("needs a name of 2 to 200 characters, ignoring surrounding spaces", () => {
    expect(validateRegistration({ ...good, name: "  A " }).name).toMatch(/at least 2/);
    expect(validateRegistration({ ...good, name: "" }).name).toBeDefined();
    expect(validateRegistration({ ...good, name: "x".repeat(201) }).name).toMatch(/200/);
    expect(validateRegistration({ ...good, name: "x".repeat(200) }).name).toBeUndefined();
  });
  it("checks the address length and characters", () => {
    expect(validateRegistration({ ...good, slug: "ab" }).slug).toMatch(/at least 3/);
    expect(validateRegistration({ ...good, slug: "a".repeat(64) }).slug).toMatch(/63/);
    expect(validateRegistration({ ...good, slug: "a".repeat(63) }).slug).toBeUndefined();
    expect(validateRegistration({ ...good, slug: "abc" }).slug).toBeUndefined();
    for (const bad of ["-abc", "abc-", "ab cd", "ab_cd", "ab.cd", "ab/cd", "বাংলা-clinic"]) {
      expect(validateRegistration({ ...good, slug: bad }).slug, bad).toMatch(/lowercase letters, digits and hyphens/);
    }
  });
  it("accepts capitals in the address, because it is lower-cased before sending", () => {
    expect(validateRegistration({ ...good, slug: "Lakeside-Clinic" }).slug).toBeUndefined();
  });
  it("needs a real time zone", () => {
    expect(validateRegistration({ ...good, timezone: "" }).timezone).toBeDefined();
    expect(validateRegistration({ ...good, timezone: "Mars/Olympus" }).timezone).toMatch(/Asia\/Dhaka/);
    expect(validateRegistration({ ...good, timezone: "UTC" }).timezone).toBeUndefined();
  });
  it("reports every problem at once", () => {
    expect(Object.keys(validateRegistration({ name: "", slug: "", timezone: "" })).sort()).toEqual(["name", "slug", "timezone"]);
  });
});

describe("registrationBody", () => {
  it("trims, lower-cases the address and sends nothing else", () => {
    expect(registrationBody({ name: "  Lakeside  ", slug: " Lake-Side ", timezone: " Asia/Dhaka " }))
      .toEqual({ name: "Lakeside", slug: "lake-side", timezone: "Asia/Dhaka" });
  });
});

describe("defaultTimeZone", () => {
  it("is always a time zone the form will accept", () => {
    expect(validateRegistration({ ...good, timezone: defaultTimeZone() }).timezone).toBeUndefined();
  });
});

describe("clinicStatusNote", () => {
  it("explains a clinic that is not open, and is silent for an open one", () => {
    expect(clinicStatusNote("PENDING")).toMatch(/Waiting for approval/);
    expect(clinicStatusNote("SUSPENDED")).toMatch(/Closed/);
    expect(clinicStatusNote("ACTIVE")).toBeNull();
    expect(clinicStatusNote(undefined)).toBeNull();
  });
});
