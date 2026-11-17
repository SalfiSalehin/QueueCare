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
