import { api } from "@/lib/api";
import type { ClinicDetail, ClinicSummary, Doctor, Page } from "@/types/api";

export const clinicService = {
  /** Open clinics, A to Z. `q` keeps those whose name or address contains every word. */
  directory: (q = "", limit = 100) => api.get<Page<ClinicSummary>>("/clinics", { limit, q }),
  get: (clinicId: string) => api.get<ClinicDetail>(`/clinics/${clinicId}`),
  join: (clinicId: string) => api.post<void>(`/clinics/${clinicId}/join`),
  doctors: (clinicId: string) => api.get<Page<Doctor>>(`/clinics/${clinicId}/doctors`, { limit: 100 }),
};
