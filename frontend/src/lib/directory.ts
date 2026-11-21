/** Helpers for the clinic search on "Find a clinic". Kept free of React so they can be unit-tested. */

/** How many clinics are shown at first, and how many more each "Show more" adds. */
export const PAGE_SIZE = 12;
/** The API rejects longer searches; the input stops people at this length. */
export const MAX_QUERY_LENGTH = 100;
/** How long to wait after the last keystroke before asking the server. */
export const DEBOUNCE_MS = 300;

/** What is sent to the API: surrounding spaces removed, runs of spaces made one, and no longer than the API accepts. */
export function cleanQuery(raw: string): string {
  return raw.replace(/\s+/g, " ").trim().slice(0, MAX_QUERY_LENGTH).trim();
}

/** The page size to ask for after "Show more". It never goes past what the API will return in one go (100). */
export function nextLimit(current: number): number {
  return Math.min(current + PAGE_SIZE, 100);
}

/** Whether there are more clinics than are on screen. */
export function hasMore(shown: number, total: number): boolean {
  return shown < total;
}

/** One line telling the person what the list is showing, for the screen and for screen readers. */
export function resultSummary(shown: number, total: number, query: string): string {
  const q = cleanQuery(query);
  const clinics = (n: number) => `${n} ${n === 1 ? "clinic" : "clinics"}`;
  if (total === 0) return q ? `No clinic matches "${q}".` : "No clinics are open yet.";
  const base = shown < total ? `Showing ${shown} of ${clinics(total)}` : `${clinics(total)}`;
  return q ? `${base} matching "${q}"` : base;
}
