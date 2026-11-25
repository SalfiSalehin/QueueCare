import { api } from "@/lib/api";
import type { ClinicDetail, ClinicRegistration, ClinicSummary, Doctor, Page } from "@/types/api";

export const clinicService = {
  /** Open clinics, A to Z. `q` keeps those whose name or address contains every word. */
  directory: (q = "", limit = 100) => api.get<Page<ClinicSummary>>("/clinics", { limit, q }),
  /** Registers a clinic. It waits for a platform administrator's approval; the caller becomes its clinic admin. */
  register: (body: ClinicRegistration) => api.post<ClinicSummary>("/clinics", body),
  get: (clinicId: string) => api.get<ClinicDetail>(`/clinics/${clinicId}`),
  join: (clinicId: string) => api.post<void>(`/clinics/${clinicId}/join`),
  doctors: (clinicId: string) => api.get<Page<Doctor>>(`/clinics/${clinicId}/doctors`, { limit: 100 }),
};
