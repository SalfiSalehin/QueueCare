import { describe, expect, it } from "vitest";
import { showDemoBanner } from "./demo";

describe("showDemoBanner", () => {
  it("is on by default and for anything but an explicit false", () => {
    expect(showDemoBanner(undefined)).toBe(true);
    expect(showDemoBanner("")).toBe(true);
    expect(showDemoBanner("true")).toBe(true);
    expect(showDemoBanner("0")).toBe(true);
    expect(showDemoBanner("flase")).toBe(true);
  });
  it("is off only when the setting says false, in any case", () => {
    expect(showDemoBanner("false")).toBe(false);
    expect(showDemoBanner(" FALSE ")).toBe(false);
  });
});
