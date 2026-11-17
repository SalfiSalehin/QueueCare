import { describe, expect, it } from "vitest";
import { actionsFor, checkInCandidates, isFrontDesk, isStaff } from "@/lib/queue-actions";

const names = (s: Parameters<typeof actionsFor>[0], r: Parameters<typeof actionsFor>[1]) => actionsFor(s, r).map((a) => a.action);

describe("actionsFor", () => {
  it("offers the legal next steps for each status", () => {
    expect(names("WAITING", "RECEPTIONIST")).toEqual(["call", "skip", "cancel"]);
    expect(names("CALLED", "RECEPTIONIST")).toEqual(["start", "skip", "no-show"]);
    expect(names("IN_CONSULTATION", "DOCTOR")).toEqual(["complete"]);
    expect(names("SKIPPED", "CLINIC_ADMIN")).toEqual(["requeue", "no-show", "cancel"]);
  });
  it("offers nothing for finished tokens", () => {
    for (const s of ["COMPLETED", "CANCELLED", "NO_SHOW"] as const) expect(names(s, "CLINIC_ADMIN")).toEqual([]);
  });
  it("never offers 'remove' to a doctor", () => {
    expect(names("WAITING", "DOCTOR")).toEqual(["call", "skip"]);
    expect(names("SKIPPED", "DOCTOR")).toEqual(["requeue", "no-show"]);
  });
});

describe("roles", () => {
  it("separates front desk and staff", () => {
    expect([isFrontDesk("RECEPTIONIST"), isFrontDesk("CLINIC_ADMIN"), isFrontDesk("DOCTOR"), isFrontDesk("PATIENT")]).toEqual([true, true, false, false]);
    expect([isStaff("DOCTOR"), isStaff("PATIENT")]).toEqual([true, false]);
  });
});

describe("checkInCandidates", () => {
  it("keeps booked appointments that are not already in the queue", () => {
    const appts = [
      { id: "a", status: "CONFIRMED" }, { id: "b", status: "CANCELLED" }, { id: "c", status: "CHECKED_IN" },
      { id: "d", status: "PENDING" }, { id: "e", status: "CONFIRMED" },
    ];
    expect(checkInCandidates(appts, new Set(["e"])).map((a) => a.id)).toEqual(["a", "d"]);
  });
});
