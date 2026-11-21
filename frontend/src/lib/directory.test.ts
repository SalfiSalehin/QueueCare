import { describe, expect, it } from "vitest";
import { cleanQuery, hasMore, MAX_QUERY_LENGTH, nextLimit, PAGE_SIZE, resultSummary } from "./directory";

describe("cleanQuery", () => {
  it("trims and squeezes spaces, tabs and new lines", () => {
    expect(cleanQuery("  city \t  dental\n care ")).toBe("city dental care");
    expect(cleanQuery("   ")).toBe("");
    expect(cleanQuery("")).toBe("");
  });
  it("keeps the person's words and case as typed", () => {
    expect(cleanQuery("North-Clinic 100%")).toBe("North-Clinic 100%");
  });
  it("never goes past the length the API accepts, and leaves no trailing space after cutting", () => {
    const long = "a".repeat(MAX_QUERY_LENGTH + 50);
    expect(cleanQuery(long)).toHaveLength(MAX_QUERY_LENGTH);
    const cutAtSpace = "a".repeat(MAX_QUERY_LENGTH - 1) + " bbb";
    expect(cleanQuery(cutAtSpace)).toBe("a".repeat(MAX_QUERY_LENGTH - 1));
  });
});

describe("paging", () => {
  it("adds a page at a time and stops at 100", () => {
    expect(nextLimit(PAGE_SIZE)).toBe(PAGE_SIZE * 2);
    expect(nextLimit(96)).toBe(100);
    expect(nextLimit(100)).toBe(100);
  });
  it("offers more only while some are hidden", () => {
    expect(hasMore(12, 30)).toBe(true);
    expect(hasMore(30, 30)).toBe(false);
    expect(hasMore(0, 0)).toBe(false);
  });
});

describe("resultSummary", () => {
  it("says what is shown, with the search words when there are any", () => {
    expect(resultSummary(3, 3, "")).toBe("3 clinics");
    expect(resultSummary(1, 1, "")).toBe("1 clinic");
    expect(resultSummary(12, 30, "")).toBe("Showing 12 of 30 clinics");
    expect(resultSummary(2, 2, "  city ")).toBe('2 clinics matching "city"');
    expect(resultSummary(12, 40, "den")).toBe('Showing 12 of 40 clinics matching "den"');
  });
  it("tells an empty search from an empty directory", () => {
    expect(resultSummary(0, 0, "zzz")).toBe('No clinic matches "zzz".');
    expect(resultSummary(0, 0, "")).toBe("No clinics are open yet.");
    expect(resultSummary(0, 0, "   ")).toBe("No clinics are open yet.");
  });
});
