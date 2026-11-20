import type { ClinicDetail, ClinicPatch, ClinicSettings, Doctor, DoctorPatch } from "@/types/api";

// Pure helpers for the clinic setup screens: validation that mirrors the API's rules (the API stays the authority),
// clinic-time conversion for time off, and small formatting helpers.

export const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

/** "09:00:00" or "09:00" -> "09:00". */
export const hhmm = (t: string): string => t.slice(0, 5);

export const windowLabel = (start: string, end: string): string => `${hhmm(start)}–${hhmm(end)}`;

const toMinutes = (t: string): number => {
  const [h, m] = hhmm(t).split(":");
  return Number(h) * 60 + Number(m);
};

export interface Window { day_of_week: number; start_time: string; end_time: string }

/** Returns a message, or null when the weekly window is acceptable. Times are clinic-local "HH:MM". */
export function validateWindow(start: string, end: string, existing: Window[], day: number): string | null {
  if (!/^\d{2}:\d{2}/.test(start) || !/^\d{2}:\d{2}/.test(end)) return "Choose a start and an end time.";
  const s = toMinutes(start);
  const e = toMinutes(end);
  if (e <= s) return "The end time must be after the start time.";
  const clash = existing.find((w) => w.day_of_week === day && s < toMinutes(w.end_time) && toMinutes(w.start_time) < e);
  if (clash) return `That overlaps ${DAY_NAMES[day] ?? "that day"} ${windowLabel(clash.start_time, clash.end_time)}.`;
  return null;
}

export function validateDepartment(name: string, prefix: string): string | null {
  const n = name.trim();
  if (n.length < 2 || n.length > 100) return "Use a name of 2 to 100 characters.";
  if (!/^[A-Za-z]{1,3}$/.test(prefix.trim())) return "The queue prefix is 1 to 3 letters, for example G.";
  return null;
}

export function validateDoctor(name: string, departmentId: string, slot: number, buffer: number): string | null {
  const n = name.trim();
  if (n.length < 2 || n.length > 120) return "Use a name of 2 to 120 characters.";
  if (!departmentId) return "Choose a department.";
  if (!Number.isInteger(slot) || slot < 5 || slot > 240) return "Appointment length must be 5 to 240 minutes.";
  if (!Number.isInteger(buffer) || buffer < 0 || buffer > 120) return "Gap between appointments must be 0 to 120 minutes.";
  return null;
}

const MAX_TIME_OFF_DAYS = 90;

/** Inputs are clinic-local "YYYY-MM-DDTHH:mm" from a datetime-local field. */
export function validateTimeOff(startLocal: string, endLocal: string, timeZone: string): string | null {
  const s = localToUtcIso(startLocal, timeZone);
  const e = localToUtcIso(endLocal, timeZone);
  if (!s || !e) return "Choose when the time off starts and ends.";
  const ms = new Date(e).getTime() - new Date(s).getTime();
  if (ms <= 0) return "The end must be after the start.";
  if (ms > MAX_TIME_OFF_DAYS * 86_400_000) return `Time off cannot be longer than ${MAX_TIME_OFF_DAYS} days.`;
  return null;
}

function offsetMinutes(utcMs: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(new Date(utcMs));
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? "0");
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return (asUtc - utcMs) / 60_000;
}

/**
 * A wall-clock time in the CLINIC's time zone ("YYYY-MM-DDTHH:mm") as a UTC ISO string, or null if it is malformed.
 * The browser's own time zone is deliberately ignored: a clinic's hours are the clinic's, wherever the admin sits.
 * In the hour that does not exist when clocks go forward the result is the nearest valid instant.
 */
export function localToUtcIso(local: string, timeZone: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!m) return null;
  const naive = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
  if (Number.isNaN(naive)) return null;
  try {
    let guess = naive - offsetMinutes(naive, timeZone) * 60_000;
    guess = naive - offsetMinutes(guess, timeZone) * 60_000;
    return new Date(guess).toISOString();
  } catch {
    return null; // unknown time zone
  }
}

// ---------------------------------------------------------------------------------------------- editing

/** True when the browser knows this IANA time zone name (for example "Asia/Dhaka"). The API checks again. */
export function isValidTimeZone(timeZone: string): boolean {
  if (!timeZone.trim()) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone });
    return true;
  } catch {
    return false;
  }
}

const isWhole = (n: number, min: number, max: number) => Number.isInteger(n) && n >= min && n <= max;

export interface ClinicForm {
  name: string; timezone: string; bookingHorizonDays: number; minNoticeMinutes: number; cancellationCutoffHours: number;
  queuePolicy: ClinicSettings["queue_policy"]; walkinPriorityEnabled: boolean;
}

export const clinicFormFrom = (c: ClinicDetail): ClinicForm => ({
  name: c.name, timezone: c.timezone, bookingHorizonDays: c.settings.booking_horizon_days,
  minNoticeMinutes: c.settings.min_notice_minutes, cancellationCutoffHours: c.settings.cancellation_cutoff_hours,
  queuePolicy: c.settings.queue_policy, walkinPriorityEnabled: c.settings.walkin_priority_enabled,
});

/** Mirrors the API's limits so a mistake is explained before any request. The API stays the authority. */
export function validateClinic(f: ClinicForm): string | null {
  const n = f.name.trim();
  if (n.length < 2 || n.length > 200) return "Use a clinic name of 2 to 200 characters.";
  if (!isValidTimeZone(f.timezone)) return "That time zone is not recognised. Use a name like Asia/Dhaka or Europe/London.";
  if (!isWhole(f.bookingHorizonDays, 1, 365)) return "Patients can book 1 to 365 days ahead.";
  if (!isWhole(f.minNoticeMinutes, 0, 1440)) return "Minimum notice must be 0 to 1440 minutes (one day).";
  if (!isWhole(f.cancellationCutoffHours, 0, 168)) return "The cancellation cut-off must be 0 to 168 hours (one week).";
  return null;
}

/** Only the fields that differ from the saved clinic, in the API's shape. An empty object means nothing changed. */
export function clinicChanges(current: ClinicDetail, f: ClinicForm): ClinicPatch {
  const patch: ClinicPatch = {};
  if (f.name.trim() !== current.name) patch.name = f.name.trim();
  if (f.timezone.trim() !== current.timezone) patch.timezone = f.timezone.trim();
  const s = current.settings;
  const settings: Partial<ClinicSettings> = {};
  if (f.bookingHorizonDays !== s.booking_horizon_days) settings.booking_horizon_days = f.bookingHorizonDays;
  if (f.minNoticeMinutes !== s.min_notice_minutes) settings.min_notice_minutes = f.minNoticeMinutes;
  if (f.cancellationCutoffHours !== s.cancellation_cutoff_hours) settings.cancellation_cutoff_hours = f.cancellationCutoffHours;
  if (f.queuePolicy !== s.queue_policy) settings.queue_policy = f.queuePolicy;
  if (f.walkinPriorityEnabled !== s.walkin_priority_enabled) settings.walkin_priority_enabled = f.walkinPriorityEnabled;
  if (Object.keys(settings).length > 0) patch.settings = settings;
  return patch;
}

export interface DoctorForm { name: string; departmentId: string; slot: number; buffer: number }

export const doctorFormFrom = (d: Doctor): DoctorForm => ({
  name: d.display_name, departmentId: d.department_id, slot: d.default_slot_minutes, buffer: d.buffer_minutes,
});

/** Only the fields that differ from the saved doctor. An empty object means nothing changed. */
export function doctorChanges(current: Doctor, f: DoctorForm): DoctorPatch {
  const patch: DoctorPatch = {};
  if (f.name.trim() !== current.display_name) patch.display_name = f.name.trim();
  if (f.departmentId !== current.department_id) patch.department_id = f.departmentId;
  if (f.slot !== current.default_slot_minutes) patch.default_slot_minutes = f.slot;
  if (f.buffer !== current.buffer_minutes) patch.buffer_minutes = f.buffer;
  return patch;
}
