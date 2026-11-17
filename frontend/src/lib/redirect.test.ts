import { describe, expect, it } from "vitest";
import { safeNext } from "@/lib/redirect";

describe("safeNext", () => {
  it("accepts relative app paths", () => {
    expect(safeNext("/app/clinics")).toBe("/app/clinics");
  });
  it("rejects open-redirect attempts", () => {
    for (const bad of ["//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)", "", null, undefined]) {
      expect(safeNext(bad as string | null | undefined)).toBe("/app");
    }
  });
});
