import { describe, expect, it } from "vitest";
import { auditLabel, clinicActions, confirmMessage, countByStatus, filterAudit, filterClinics, isClinicEvent, isPlatformAdmin, statusLabel, STATUS_FILTERS } from "./platform";

describe("who is a platform administrator", () => {
  it("only the SUPER_ADMIN role", () => {
    expect(isPlatformAdmin({ platform_role: "SUPER_ADMIN" })).toBe(true);
    expect(isPlatformAdmin({ platform_role: "NONE" })).toBe(false);
    expect(isPlatformAdmin({ platform_role: "super_admin" })).toBe(false);
    expect(isPlatformAdmin(undefined)).toBe(false);
    expect(isPlatformAdmin(null)).toBe(false);
  });
});

describe("clinic status wording", () => {
  it("uses plain words, and shows an unknown status rather than hiding it", () => {
    expect(statusLabel("PENDING")).toBe("Waiting for approval");
    expect(statusLabel("ACTIVE")).toBe("Open");
    expect(statusLabel("SUSPENDED")).toBe("Suspended");
    expect(statusLabel("SOMETHING_NEW")).toBe("something new");
  });
  it("offers a filter for every status plus all", () => {
    expect(STATUS_FILTERS.map((f) => f.id)).toEqual(["PENDING", "ACTIVE", "SUSPENDED", "ALL"]);
  });
});

describe("what can be done to a clinic", () => {
  it("a waiting clinic can be approved straight away or declined after a warning", () => {
    expect(clinicActions("PENDING")).toEqual([
      { to: "ACTIVE", label: "Approve", confirm: false },
      { to: "SUSPENDED", label: "Decline", confirm: true },
    ]);
  });
  it("an open clinic can only be suspended, and only after a warning", () => {
    expect(clinicActions("ACTIVE")).toEqual([{ to: "SUSPENDED", label: "Suspend", confirm: true }]);
  });
  it("a suspended clinic can be reopened straight away", () => {
    expect(clinicActions("SUSPENDED")).toEqual([{ to: "ACTIVE", label: "Reactivate", confirm: false }]);
  });
  it("an unknown status offers nothing", () => {
    expect(clinicActions("MYSTERY")).toEqual([]);
  });
  it("every action that locks people out asks first, and none that opens a clinic does", () => {
    for (const status of ["PENDING", "ACTIVE", "SUSPENDED"]) {
      for (const a of clinicActions(status)) expect(a.confirm).toBe(a.to !== "ACTIVE");
    }
  });
  it("the warning names the clinic and says what happens", () => {
    const m = confirmMessage("Synthetic Clinic", { to: "SUSPENDED", label: "Suspend", confirm: true });
    expect(m).toMatch(/Suspend Synthetic Clinic\?/);
    expect(m).toMatch(/cannot use it/);
    expect(m).toMatch(/data is kept/);
  });
});

describe("counting and filtering", () => {
  const clinics = [{ status: "PENDING" }, { status: "ACTIVE" }, { status: "ACTIVE" }, { status: "SUSPENDED" }, { status: "ODD" }];
  it("counts each status, and counts everything under All", () => {
    expect(countByStatus(clinics)).toEqual({ PENDING: 1, ACTIVE: 2, SUSPENDED: 1, ALL: 5 });
    expect(countByStatus([])).toEqual({ PENDING: 0, ACTIVE: 0, SUSPENDED: 0, ALL: 0 });
  });
  it("filters by status, and All keeps every clinic", () => {
    expect(filterClinics(clinics, "ACTIVE")).toHaveLength(2);
    expect(filterClinics(clinics, "PENDING")).toEqual([{ status: "PENDING" }]);
    expect(filterClinics(clinics, "ALL")).toHaveLength(5);
  });
});

describe("activity wording", () => {
  it("names the known action and makes unknown ones readable", () => {
    expect(auditLabel("platform.clinic_status_changed")).toBe("Clinic status changed");
    expect(auditLabel("platform.user_locked_out")).toBe("User locked out");
    expect(auditLabel("login")).toBe("Login");
    expect(auditLabel("")).toBe("");
  });
  it("gives every known action a clear label", () => {
    expect(auditLabel("clinic.registered")).toBe("Clinic registered");
    expect(auditLabel("auth.login")).toBe("Signed in");
    expect(auditLabel("auth.login_failed")).toBe("Failed sign-in");
    expect(auditLabel("clinic.patient_joined")).toBe("Patient joined a clinic");
  });
  it("separates clinic changes from sign-in and account events", () => {
    for (const a of ["platform.clinic_status_changed", "clinic.registered", "clinic.member_added", "patient.created"]) expect(isClinicEvent(a)).toBe(true);
    for (const a of ["auth.login", "auth.logout", "auth.password_reset", "", "clinicx.thing", "xplatform.y"]) expect(isClinicEvent(a)).toBe(false);
  });
  it("hides account events by default and shows everything when asked", () => {
    const events = [{ action: "auth.login" }, { action: "clinic.registered" }, { action: "auth.logout" }, { action: "platform.clinic_status_changed" }];
    expect(filterAudit(events, false).map((e) => e.action)).toEqual(["clinic.registered", "platform.clinic_status_changed"]);
    expect(filterAudit(events, true)).toHaveLength(4);
    expect(filterAudit([], false)).toEqual([]);
  });
});
