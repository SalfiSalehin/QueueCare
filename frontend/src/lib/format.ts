// Dates arrive as UTC ISO strings. Always display them in the CLINIC's time zone, never the browser's.

export function formatDateTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(iso));
}

export function formatTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
}

/** Clinic-local calendar day as YYYY-MM-DD (used to group slots). */
export function localDay(iso: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(iso));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Heading for a YYYY-MM-DD calendar day. Formatted at noon UTC so the date cannot shift across time zones. */
export function formatDayHeading(day: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "long", day: "numeric", month: "long" })
    .format(new Date(`${day}T12:00:00Z`));
}

export function groupByDay<T>(items: T[], getIso: (item: T) => string, timeZone: string): [string, T[]][] {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const day = localDay(getIso(item), timeZone);
    const list = map.get(day);
    if (list) list.push(item); else map.set(day, [item]);
  }
  return [...map.entries()].sort(([a], [b]) => (a < b ? -1 : 1));
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function dayOf(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone, day: "numeric" }).format(new Date(iso));
}

export function monthOf(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone, month: "short" }).format(new Date(iso));
}
