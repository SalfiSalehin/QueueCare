import { describe, expect, it } from "vitest";
import { barWidths, daysBack, driftTone, hourLabel, mins, pct, signed, suggestionTone } from "@/lib/insights";

describe("daysBack", () => {
  it("covers N calendar days inclusive of today", () => {
    expect(daysBack("2026-11-15", 7)).toEqual({ start: "2026-11-09", end: "2026-11-15" });
    expect(daysBack("2026-11-15", 1)).toEqual({ start: "2026-11-15", end: "2026-11-15" });
  });
  it("crosses month and year boundaries", () => {
    expect(daysBack("2027-01-03", 7)).toEqual({ start: "2026-12-28", end: "2027-01-03" });
    expect(daysBack("2026-03-02", 30).start).toBe("2026-02-01");
  });
});

describe("formatting", () => {
  it("never turns missing data into zero", () => {
    expect(pct(null)).toBe("–");
    expect(mins(undefined)).toBe("–");
    expect(signed(null)).toBe("–");
    expect(pct(0)).toBe("0%");
  });
  it("formats values", () => {
    expect(pct(0.1234)).toBe("12%");
    expect(pct(0.1234, 1)).toBe("12.3%");
    expect(mins(12.4)).toBe("12 min");
    expect(signed(2.345, " min")).toBe("+2.3 min");
    expect(signed(-4, " min")).toBe("−4.0 min");
    expect(signed(0.01)).toBe("0");
    expect(hourLabel(9)).toBe("09:00");
  });
});

describe("barWidths", () => {
  it("scales to the largest value", () => {
    expect(barWidths([5, 10, 0])).toEqual([50, 100, 0]);
  });
  it("keeps tiny non-zero values visible and handles all-zero or empty input", () => {
    expect(barWidths([1, 1000])).toEqual([3, 100]);
    expect(barWidths([0, 0])).toEqual([0, 0]);
    expect(barWidths([])).toEqual([]);
  });
});

describe("tones", () => {
  it("maps backend statuses to tones, unknown ones to neutral", () => {
    expect([driftTone("stable"), driftTone("moderate"), driftTone("high"), driftTone("insufficient_data")]).toEqual(["good", "watch", "bad", "neutral"]);
    expect([driftTone("ok"), driftTone("watch"), driftTone("degraded")]).toEqual(["good", "watch", "bad"]);
    expect([suggestionTone("keep"), suggestionTone("lengthen"), suggestionTone("shorten"), suggestionTone("insufficient_data")]).toEqual(["good", "watch", "watch", "neutral"]);
  });
});
