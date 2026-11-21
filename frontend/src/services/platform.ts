import { api } from "@/lib/api";
import type { ClinicStatus, ClinicSummary, PlatformAuditEntry } from "@/types/api";

/** Platform administrator endpoints. The API refuses everyone else, whatever the page shows. */
export const platformService = {
  clinics: (status?: ClinicStatus) => api.get<ClinicSummary[]>("/platform/clinics", status ? { status } : undefined),
  setStatus: (clinicId: string, status: ClinicStatus) => api.post<ClinicSummary>(`/platform/clinics/${clinicId}/status`, { status }),
  audit: (limit = 100) => api.get<PlatformAuditEntry[]>("/platform/audit-logs", { limit }),
};
