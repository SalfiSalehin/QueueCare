import { api } from "@/lib/api";
import type { ClinicDetail, ClinicSummary, Doctor, Page } from "@/types/api";

export const clinicService = {
  directory: () => api.get<Page<ClinicSummary>>("/clinics", { limit: 100 }),
  get: (clinicId: string) => api.get<ClinicDetail>(`/clinics/${clinicId}`),
  join: (clinicId: string) => api.post<void>(`/clinics/${clinicId}/join`),
  doctors: (clinicId: string) => api.get<Page<Doctor>>(`/clinics/${clinicId}/doctors`, { limit: 100 }),
};
