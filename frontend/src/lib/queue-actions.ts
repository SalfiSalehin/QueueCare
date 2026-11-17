import type { ClinicRole, QueueAction, QueueStatus } from "@/types/api";

export interface ActionSpec { action: QueueAction; label: string; variant: "primary" | "secondary" | "danger" }

// Mirrors backend/app/services/queue_logic.py. The server stays the authority: this only decides which buttons to
// show, and a stale screen that sends a no-longer-valid action just gets a 409 that is displayed to the user.
const BY_STATUS: Partial<Record<QueueStatus, ActionSpec[]>> = {
  WAITING: [
    { action: "call", label: "Call", variant: "primary" },
    { action: "skip", label: "Skip", variant: "secondary" },
    { action: "cancel", label: "Remove", variant: "danger" },
  ],
  CALLED: [
    { action: "start", label: "Start", variant: "primary" },
    { action: "skip", label: "Skip", variant: "secondary" },
    { action: "no-show", label: "No-show", variant: "danger" },
  ],
  IN_CONSULTATION: [{ action: "complete", label: "Complete", variant: "primary" }],
  SKIPPED: [
    { action: "requeue", label: "Back to queue", variant: "primary" },
    { action: "no-show", label: "No-show", variant: "danger" },
    { action: "cancel", label: "Remove", variant: "danger" },
  ],
};

/** Doctors cannot cancel (remove) a token; only the front desk can. */
export function actionsFor(status: QueueStatus, role: ClinicRole): ActionSpec[] {
  const list = BY_STATUS[status] ?? [];
  return role === "DOCTOR" ? list.filter((a) => a.action !== "cancel") : list;
}

export const isFrontDesk = (role: ClinicRole): boolean => role === "CLINIC_ADMIN" || role === "RECEPTIONIST";
export const isStaff = (role: ClinicRole): boolean => role !== "PATIENT";

/** Appointments the front desk can check in today: booked and not yet arrived. */
export function checkInCandidates<T extends { status: string; id: string }>(appts: T[], alreadyQueued: Set<string>): T[] {
  return appts.filter((a) => (a.status === "CONFIRMED" || a.status === "PENDING") && !alreadyQueued.has(a.id));
}
