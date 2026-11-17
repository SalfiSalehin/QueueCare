import type { Scenario } from "@/types/api";

// Bounds mirror backend/app/schemas/simulation.py (the server re-validates everything).
export const BOUNDS = {
  doctors: { min: 1, max: 6, step: 1, label: "Doctors in the sample" },
  days: { min: 5, max: 30, step: 1, label: "Days simulated" },
  mean_service_minutes: { min: 5, max: 40, step: 0.5, label: "Average visit length (min)" },
  slot_minutes: { min: 5, max: 60, step: 5, label: "Booked slot length (min)" },
  booked_share: { min: 0, max: 1, step: 0.05, label: "Share of visits that are booked" },
  walk_in_per_hour: { min: 0, max: 4, step: 0.5, label: "Walk-ins per hour" },
  seed: { min: 0, max: 1_000_000, step: 1, label: "Random seed" },
} as const;

export const MAX_SCENARIOS = 3;

const INTEGER_FIELDS = new Set<keyof typeof BOUNDS>(["doctors", "days", "slot_minutes", "seed"]);

/** The first field that is missing, not a finite number, not a whole number where one is required, or out of range. */
function badField(s: Scenario): keyof typeof BOUNDS | null {
  for (const key of Object.keys(BOUNDS) as (keyof typeof BOUNDS)[]) {
    const v = s[key];
    const { min, max } = BOUNDS[key];
    if (typeof v !== "number" || !Number.isFinite(v) || v < min || v > max) return key;
    if (INTEGER_FIELDS.has(key) && !Number.isInteger(v)) return key;
  }
  return null;
}

export const defaultScenario = (name = "Baseline"): Scenario => ({
  name, doctors: 3, days: 20, mean_service_minutes: 12, slot_minutes: 15, booked_share: 0.65, walk_in_per_hour: 1, seed: 1,
});

/** A second scenario that changes only the walk-in rate, so the comparison isolates one thing. */
export const comparisonScenario = (base: Scenario): Scenario => ({ ...base, name: "More walk-ins", walk_in_per_hour: Math.min(4, base.walk_in_per_hour + 1) });

/** Returns the first problem as a sentence, or null when every scenario is valid and names are unique. */
export function validateScenarios(list: Scenario[]): string | null {
  if (list.length < 1 || list.length > MAX_SCENARIOS) return `Use between 1 and ${MAX_SCENARIOS} scenarios.`;
  const names = new Set<string>();
  for (const [i, s] of list.entries()) {
    const name = s.name.trim();
    if (name.length < 1 || name.length > 60) return `Scenario ${i + 1}: give it a name of 1 to 60 characters.`;
    const bad = badField(s);
    if (bad) return `Scenario ${i + 1}: ${BOUNDS[bad].label} is out of range or missing.`;
    if (names.has(name.toLowerCase())) return "Scenario names must be different, so the results can be told apart.";
    names.add(name.toLowerCase());
  }
  return null;
}
