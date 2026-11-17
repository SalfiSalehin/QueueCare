import { describe, expect, it } from "vitest";
import { DAY_NAMES, hhmm, localToUtcIso, validateDepartment, validateDoctor, validateTimeOff, validateWindow, windowLabel } from "./setup";

describe("windows", () => {
  it("formats times", () => {
    expect(hhmm("09:00:00")).toBe("09:00");
    expect(windowLabel("09:00:00", "17:30:00")).toBe("09:00–17:30");
    expect(DAY_NAMES[0]).toBe("Monday");
  });
  it("rejects missing, reversed and empty windows", () => {
    expect(validateWindow("", "10:00", [], 0)).toMatch(/Choose/);
    expect(validateWindow("10:00", "09:00", [], 0)).toMatch(/after the start/);
    expect(validateWindow("10:00", "10:00", [], 0)).toMatch(/after the start/);
    expect(validateWindow("09:00", "10:00", [], 0)).toBeNull();
  });
  it("rejects an overlap on the same day only", () => {
    const existing = [{ day_of_week: 1, start_time: "09:00:00", end_time: "12:00:00" }];
    expect(validateWindow("11:00", "13:00", existing, 1)).toMatch(/overlaps Tuesday 09:00–12:00/);
    expect(validateWindow("12:00", "13:00", existing, 1)).toBeNull(); // touching is fine
    expect(validateWindow("11:00", "13:00", existing, 2)).toBeNull(); // another day
  });
});

describe("department and doctor rules", () => {
  it("checks the department name and prefix", () => {
    expect(validateDepartment("G", "G")).toMatch(/name/);
    expect(validateDepartment("General", "")).toMatch(/prefix/);
    expect(validateDepartment("General", "ABCD")).toMatch(/prefix/);
    expect(validateDepartment("General", "g1")).toMatch(/prefix/);
    expect(validateDepartment("General", "g")).toBeNull();
  });
  it("checks doctor fields", () => {
    expect(validateDoctor("D", "d1", 15, 5)).toMatch(/name/);
    expect(validateDoctor("Dr Synthetic", "", 15, 5)).toMatch(/department/);
    expect(validateDoctor("Dr Synthetic", "d1", 4, 5)).toMatch(/5 to 240/);
    expect(validateDoctor("Dr Synthetic", "d1", 15, 121)).toMatch(/0 to 120/);
    expect(validateDoctor("Dr Synthetic", "d1", 15.5, 5)).toMatch(/5 to 240/);
    expect(validateDoctor("Dr Synthetic", "d1", 30, 0)).toBeNull();
  });
});

describe("clinic time conversion", () => {
  it("converts a clinic wall-clock time to UTC using the clinic's zone", () => {
    expect(localToUtcIso("2026-11-20T09:00", "Asia/Dhaka")).toBe("2026-11-20T03:00:00.000Z");
    expect(localToUtcIso("2026-11-20T09:00", "UTC")).toBe("2026-11-20T09:00:00.000Z");
  });
  it("follows daylight saving in the clinic's zone", () => {
    expect(localToUtcIso("2026-01-15T09:00", "America/New_York")).toBe("2026-01-15T14:00:00.000Z");
    expect(localToUtcIso("2026-07-15T09:00", "America/New_York")).toBe("2026-07-15T13:00:00.000Z");
  });
  it("returns null for malformed input or an unknown zone", () => {
    expect(localToUtcIso("2026-11-20 09:00", "UTC")).toBeNull();
    expect(localToUtcIso("", "UTC")).toBeNull();
    expect(localToUtcIso("2026-11-20T09:00", "Not/AZone")).toBeNull();
  });
});

describe("time off", () => {
  it("validates order and the 90-day cap", () => {
    expect(validateTimeOff("", "", "UTC")).toMatch(/Choose/);
    expect(validateTimeOff("2026-11-20T10:00", "2026-11-20T09:00", "UTC")).toMatch(/after the start/);
    expect(validateTimeOff("2026-11-20T09:00", "2027-03-20T09:00", "UTC")).toMatch(/90 days/);
    expect(validateTimeOff("2026-11-20T09:00", "2026-11-22T17:00", "UTC")).toBeNull();
  });
});
