import { describe, expect, it } from "vitest";
import { loginSchema, registerSchema } from "@/lib/auth-schemas";

/** First error message per field, the way the forms show it. */
function firstErrors(result: { success: boolean; error?: { issues: { path: PropertyKey[]; message: string }[] } }) {
  const out: Record<string, string> = {};
  for (const i of result.error?.issues ?? []) {
    const key = String(i.path[0]);
    if (!(key in out)) out[key] = i.message;
  }
  return out;
}

describe("loginSchema", () => {
  it("accepts an email and a password", () => {
    expect(loginSchema.safeParse({ email: "a@example.com", password: "x" }).success).toBe(true);
  });
  it("asks for both fields when they are empty", () => {
    expect(firstErrors(loginSchema.safeParse({ email: "", password: "" }))).toEqual({
      email: "Enter your email", password: "Enter your password",
    });
  });
  it("rejects a malformed email with its own message", () => {
    expect(firstErrors(loginSchema.safeParse({ email: "not-an-email", password: "x" }))).toEqual({
      email: "Enter a valid email address",
    });
  });
});

describe("registerSchema", () => {
  const good = { full_name: "Demo Person", email: "demo@example.com", password: "a-long-enough-pass" };
  it("accepts valid input", () => {
    expect(registerSchema.safeParse(good).success).toBe(true);
  });
  it("trims the name and rejects a blank one", () => {
    expect(registerSchema.parse({ ...good, full_name: "  Demo  " }).full_name).toBe("Demo");
    expect(firstErrors(registerSchema.safeParse({ ...good, full_name: "   " }))).toEqual({ full_name: "Enter your name" });
  });
  it("limits the name to 200 characters", () => {
    expect(registerSchema.safeParse({ ...good, full_name: "x".repeat(200) }).success).toBe(true);
    expect(registerSchema.safeParse({ ...good, full_name: "x".repeat(201) }).success).toBe(false);
  });
  it("requires at least 12 characters in the password", () => {
    expect(registerSchema.safeParse({ ...good, password: "x".repeat(11) }).success).toBe(false);
    expect(firstErrors(registerSchema.safeParse({ ...good, password: "short" }))).toEqual({ password: "Use at least 12 characters" });
    expect(registerSchema.safeParse({ ...good, password: "x".repeat(12) }).success).toBe(true);
  });
  it("shows the empty-email message first, not the invalid-email one", () => {
    expect(firstErrors(registerSchema.safeParse({ ...good, email: "" }))).toEqual({ email: "Enter your email" });
  });
});
