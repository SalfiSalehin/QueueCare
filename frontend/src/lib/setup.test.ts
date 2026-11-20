import { describe, expect, it } from "vitest";
import {
  DAY_NAMES, clinicChanges, clinicFormFrom, doctorChanges, doctorFormFrom, hhmm, isValidTimeZone, localToUtcIso,
  validateClinic, validateDepartment, validateDoctor, validateTimeOff, validateWindow, windowLabel,
} from "./setup";
import type { ClinicDetail, Doctor } from "@/types/api";

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

const clinic: ClinicDetail = {
  id: "c1", name: "Synthetic Clinic", slug: "synthetic", status: "ACTIVE", timezone: "Asia/Dhaka", created_at: "2026-01-01T00:00:00Z",
  settings: { booking_horizon_days: 60, min_notice_minutes: 60, cancellation_cutoff_hours: 2, queue_policy: "APPOINTMENT_FIRST", walkin_priority_enabled: false },
};
const doctor: Doctor = {
  id: "d1", department_id: "dep1", display_name: "Dr Synthetic", default_slot_minutes: 15, buffer_minutes: 5,
  status: "AVAILABLE", current_delay_minutes: 0, is_active: true, has_account: false,
};

describe("time zones", () => {
  it("accepts real IANA names and rejects nonsense", () => {
    expect(isValidTimeZone("Asia/Dhaka")).toBe(true);
    expect(isValidTimeZone("Europe/London")).toBe(true);
    expect(isValidTimeZone("Mars/Olympus")).toBe(false);
    expect(isValidTimeZone("")).toBe(false);
    expect(isValidTimeZone("   ")).toBe(false);
  });
});

describe("editing the clinic", () => {
  it("starts from the saved values and finds no changes", () => {
    expect(clinicChanges(clinic, clinicFormFrom(clinic))).toEqual({});
    expect(validateClinic(clinicFormFrom(clinic))).toBeNull();
  });
  it("sends only what changed, and trims the name", () => {
    const f = { ...clinicFormFrom(clinic), name: "  New Name ", minNoticeMinutes: 90, walkinPriorityEnabled: true };
    expect(clinicChanges(clinic, f)).toEqual({ name: "New Name", settings: { min_notice_minutes: 90, walkin_priority_enabled: true } });
  });
  it("a name that only differs by spaces is not a change", () => {
    expect(clinicChanges(clinic, { ...clinicFormFrom(clinic), name: " Synthetic Clinic " })).toEqual({});
  });
  it("sends a changed time zone and queue policy", () => {
    const f = { ...clinicFormFrom(clinic), timezone: "Europe/London", queuePolicy: "FIFO" as const };
    expect(clinicChanges(clinic, f)).toEqual({ timezone: "Europe/London", settings: { queue_policy: "FIFO" } });
  });
  it("checks each limit the API enforces", () => {
    const f = clinicFormFrom(clinic);
    expect(validateClinic({ ...f, name: "A" })).toMatch(/name/);
    expect(validateClinic({ ...f, timezone: "Nowhere/Land" })).toMatch(/time zone/);
    expect(validateClinic({ ...f, bookingHorizonDays: 0 })).toMatch(/1 to 365/);
    expect(validateClinic({ ...f, bookingHorizonDays: 366 })).toMatch(/1 to 365/);
    expect(validateClinic({ ...f, minNoticeMinutes: -1 })).toMatch(/0 to 1440/);
    expect(validateClinic({ ...f, cancellationCutoffHours: 169 })).toMatch(/0 to 168/);
    expect(validateClinic({ ...f, cancellationCutoffHours: 1.5 })).toMatch(/0 to 168/);
    expect(validateClinic({ ...f, bookingHorizonDays: Number.NaN })).toMatch(/1 to 365/);
    expect(validateClinic({ ...f, minNoticeMinutes: 0, cancellationCutoffHours: 0, bookingHorizonDays: 365 })).toBeNull();
  });
});

describe("editing a doctor", () => {
  it("finds no change when nothing was touched", () => {
    expect(doctorChanges(doctor, doctorFormFrom(doctor))).toEqual({});
  });
  it("sends only the changed fields", () => {
    expect(doctorChanges(doctor, { ...doctorFormFrom(doctor), name: " Dr Renamed ", slot: 20 })).toEqual({ display_name: "Dr Renamed", default_slot_minutes: 20 });
    expect(doctorChanges(doctor, { ...doctorFormFrom(doctor), departmentId: "dep2", buffer: 0 })).toEqual({ department_id: "dep2", buffer_minutes: 0 });
  });
  it("a buffer of zero is a real change, not a missing value", () => {
    expect(doctorChanges(doctor, { ...doctorFormFrom(doctor), buffer: 0 })).toEqual({ buffer_minutes: 0 });
  });
});
