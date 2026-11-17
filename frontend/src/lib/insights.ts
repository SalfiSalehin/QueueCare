// Small pure helpers for the admin screens: ranges, number formatting and bar sizing.

/** Inclusive clinic-local date range ending today and covering `days` calendar days. `today` is YYYY-MM-DD. */
export function daysBack(today: string, days: number): { start: string; end: string } {
  const end = new Date(`${today}T12:00:00Z`);            // noon UTC: adding days never crosses a date boundary
  const start = new Date(end.getTime() - (days - 1) * 86_400_000);
  return { start: start.toISOString().slice(0, 10), end: today };
}

/** 0.1234 -> "12%". Null means "no data", never zero. */
export function pct(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "–" : `${(value * 100).toFixed(digits)}%`;
}

export function mins(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "–" : `${value.toFixed(digits)} min`;
}

/** Signed change with a real minus sign; "–" when there is nothing to compare. */
export function signed(value: number | null | undefined, unit = "", digits = 1): string {
  if (value === null || value === undefined) return "–";
  if (Math.abs(value) < 0.05) return `0${unit}`;
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}${unit}`;
}

/** Bar widths as percentages of the largest value. Non-zero values never shrink below 3% so they stay visible. */
export function barWidths(values: number[]): number[] {
  const max = Math.max(0, ...values);
  if (max === 0) return values.map(() => 0);
  return values.map((v) => (v <= 0 ? 0 : Math.max(3, Math.round((v / max) * 100))));
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;
export const hourLabel = (h: number): string => `${String(h).padStart(2, "0")}:00`;

export type Tone = "good" | "watch" | "bad" | "neutral";

/** PSI rule of thumb used by the backend: stable < 0.1 <= moderate < 0.25 <= high. */
export function driftTone(status: string): Tone {
  if (status === "stable" || status === "ok") return "good";
  if (status === "moderate" || status === "watch") return "watch";
  if (status === "high" || status === "degraded") return "bad";
  return "neutral";
}

export function suggestionTone(status: string): Tone {
  if (status === "keep") return "good";
  if (status === "lengthen" || status === "shorten") return "watch";
  return "neutral";
}
