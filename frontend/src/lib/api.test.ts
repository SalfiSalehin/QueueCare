import { describe, expect, it } from "vitest";
import { ApiError, buildUrl, parseError, readCookie } from "@/lib/api";

describe("api helpers", () => {
  it("reads a cookie value by name, including '=' inside the value", () => {
    expect(readCookie("qc_csrf", "a=1; qc_csrf=abc.def=ghi; b=2")).toBe("abc.def=ghi");
    expect(readCookie("missing", "a=1")).toBeUndefined();
  });

  it("builds URLs and drops empty query values", () => {
    expect(buildUrl("/x", { a: 1, b: undefined, c: "", d: "y z" })).toBe("/api/v1/x?a=1&d=y+z");
    expect(buildUrl("/x")).toBe("/api/v1/x");
  });

  it("turns the backend error body into an ApiError", async () => {
    const res = new Response(JSON.stringify({ error: { code: "conflict", message: "Slot taken", request_id: "r1" } }), { status: 409 });
    const err = await parseError(res);
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.code, err.message, err.requestId]).toEqual([409, "conflict", "Slot taken", "r1"]);
  });

  it("copes with a non-JSON error body", async () => {
    const err = await parseError(new Response("<html>bad gateway</html>", { status: 502 }));
    expect(err.status).toBe(502);
    expect(err.message).toContain("502");
  });
});
