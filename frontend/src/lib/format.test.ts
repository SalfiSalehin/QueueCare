import { describe, expect, it } from "vitest";
import { groupByDay, localDay, plural } from "@/lib/format";

describe("format", () => {
  it("groups by the clinic's calendar day, not the browser's", () => {
    // 23:30 UTC on 1 Jan is already 2 Jan in Dhaka (UTC+6) but still 1 Jan in London.
    expect(localDay("2030-01-01T23:30:00Z", "Asia/Dhaka")).toBe("2030-01-02");
    expect(localDay("2030-01-01T23:30:00Z", "Europe/London")).toBe("2030-01-01");
  });

  it("returns days in order with their items", () => {
    const items = ["2030-01-02T05:00:00Z", "2030-01-01T05:00:00Z", "2030-01-01T06:00:00Z"];
    const grouped = groupByDay(items, (x) => x, "UTC");
    expect(grouped.map(([d]) => d)).toEqual(["2030-01-01", "2030-01-02"]);
    expect(grouped[0]?.[1]).toHaveLength(2);
  });

  it("pluralises", () => {
    expect(plural(1, "person", "people")).toBe("1 person");
    expect(plural(3, "person", "people")).toBe("3 people");
    expect(plural(0, "slot")).toBe("0 slots");
  });
});

import { dayOf, monthOf } from "@/lib/format";

describe("dayOf / monthOf", () => {
  it("use the clinic's time zone, so a late-evening UTC time can be the next day there", () => {
    const iso = "2026-11-14T20:30:00Z";
    expect([dayOf(iso, "UTC"), monthOf(iso, "UTC")]).toEqual(["14", "Nov"]);
    expect([dayOf(iso, "Asia/Dhaka"), monthOf(iso, "Asia/Dhaka")]).toEqual(["15", "Nov"]);
  });
});
