import type { ClinicStatus, ClinicSummary, User } from "@/types/api";

// Pure helpers for the platform administrator screens. The API decides who may do what; these only choose wording
// and which buttons make sense for a clinic's current status.

export const isPlatformAdmin = (user: Pick<User, "platform_role"> | undefined | null): boolean => user?.platform_role === "SUPER_ADMIN";

export type StatusFilter = ClinicStatus | "ALL";
export const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "PENDING", label: "Waiting for approval" },
  { id: "ACTIVE", label: "Open" },
  { id: "SUSPENDED", label: "Suspended" },
  { id: "ALL", label: "All" },
];

export function statusLabel(status: string): string {
  switch (status) {
    case "PENDING": return "Waiting for approval";
    case "ACTIVE": return "Open";
    case "SUSPENDED": return "Suspended";
    default: return status.replace(/_/g, " ").toLowerCase();
  }
}

export interface StatusAction { to: ClinicStatus; label: string; /** Ask "are you sure" first: the change locks people out. */ confirm: boolean }

/** What a platform administrator can do next to a clinic in this status. */
export function clinicActions(status: string): StatusAction[] {
  switch (status) {
    case "PENDING": return [{ to: "ACTIVE", label: "Approve", confirm: false }, { to: "SUSPENDED", label: "Decline", confirm: true }];
    case "ACTIVE": return [{ to: "SUSPENDED", label: "Suspend", confirm: true }];
    case "SUSPENDED": return [{ to: "ACTIVE", label: "Reactivate", confirm: false }];
    default: return [];
  }
}

/** The plain-words warning shown before a change that locks people out. */
export function confirmMessage(clinicName: string, action: StatusAction): string {
  return `${action.label} ${clinicName}? Its staff and patients cannot use it until it is open again, and it disappears from the list patients search. Its data is kept.`;
}

export function countByStatus(clinics: Pick<ClinicSummary, "status">[]): Record<StatusFilter, number> {
  const counts: Record<StatusFilter, number> = { PENDING: 0, ACTIVE: 0, SUSPENDED: 0, ALL: clinics.length };
  for (const c of clinics) if (c.status === "PENDING" || c.status === "ACTIVE" || c.status === "SUSPENDED") counts[c.status] += 1;
  return counts;
}

export function filterClinics<T extends Pick<ClinicSummary, "status">>(clinics: T[], filter: StatusFilter): T[] {
  return filter === "ALL" ? clinics : clinics.filter((c) => c.status === filter);
}

const AUDIT_LABELS: Record<string, string> = {
  "platform.clinic_status_changed": "Clinic status changed",
  "clinic.registered": "Clinic registered",
  "clinic.member_added": "Staff member added",
  "clinic.patient_joined": "Patient joined a clinic",
  "patient.created": "Patient record created",
  "auth.register": "Account registered",
  "auth.login": "Signed in",
  "auth.login_failed": "Failed sign-in",
  "auth.login_blocked": "Sign-in blocked",
  "auth.logout": "Signed out",
  "auth.logout_all": "Signed out everywhere",
  "auth.session_revoked": "Session revoked",
  "auth.refresh_reuse_detected": "Session reuse detected",
  "auth.password_reset_requested": "Password reset requested",
  "auth.password_reset": "Password reset",
  "auth.email_verified": "Email verified",
};

/** Events about clinics and their people. Sign-ins and account events ("auth.*") are noise when looking for approvals. */
export const isClinicEvent = (action: string): boolean => /^(platform|clinic|patient)\./.test(action);

export function filterAudit<T extends { action: string }>(entries: T[], includeAll: boolean): T[] {
  return includeAll ? entries : entries.filter((e) => isClinicEvent(e.action));
}

/** Readable text for an audit action such as "platform.clinic_status_changed". Unknown actions are shown, not hidden. */
export function auditLabel(action: string): string {
  const hit = AUDIT_LABELS[action];
  if (hit) return hit;
  const last = action.split(".").pop() ?? action;
  const words = last.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : action;
}
