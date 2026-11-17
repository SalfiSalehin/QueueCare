import { describe, expect, it } from "vitest";
import { comparisonScenario, defaultScenario, validateScenarios } from "@/lib/simulation";

describe("validateScenarios", () => {
  it("accepts the defaults and a comparison", () => {
    const base = defaultScenario();
    expect(validateScenarios([base])).toBeNull();
    expect(validateScenarios([base, comparisonScenario(base)])).toBeNull();
  });
  it("rejects out-of-range values with a readable sentence", () => {
    expect(validateScenarios([{ ...defaultScenario(), doctors: 9 }])).toBe("Scenario 1: Doctors in the sample is out of range or missing.");
    expect(validateScenarios([{ ...defaultScenario(), booked_share: 1.5 }])).toContain("Share of visits");
    expect(validateScenarios([{ ...defaultScenario(), mean_service_minutes: Number.NaN }])).toContain("Average visit length");
  });
  it("rejects empty names, duplicate names and the wrong number of scenarios", () => {
    expect(validateScenarios([{ ...defaultScenario(), name: "  " }])).toContain("Scenario 1");
    expect(validateScenarios([defaultScenario("A"), defaultScenario("a")])).toContain("different");
    expect(validateScenarios([])).toContain("between 1 and 3");
    expect(validateScenarios([1, 2, 3, 4].map((n) => defaultScenario(`S${n}`)))).toContain("between 1 and 3");
  });
  it("the comparison changes only the walk-in rate and caps at the maximum", () => {
    const base = defaultScenario();
    expect(comparisonScenario(base)).toEqual({ ...base, name: "More walk-ins", walk_in_per_hour: 2 });
    expect(comparisonScenario({ ...base, walk_in_per_hour: 4 }).walk_in_per_hour).toBe(4);
  });
});
