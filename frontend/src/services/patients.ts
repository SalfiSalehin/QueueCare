import { api } from "@/lib/api";
import type { Appointment, Page, Patient } from "@/types/api";

export const patientService = {
  search: (clinicId: string, q: string) => api.get<Page<Patient>>(`/clinics/${clinicId}/patients`, { q, limit: 8 }),
  create: (clinicId: string, fullName: string, phone: string | null) =>
    api.post<Patient>(`/clinics/${clinicId}/patients`, { full_name: fullName, phone }),
  /** Appointments for one clinic-local calendar day (YYYY-MM-DD). Front desk sees the whole clinic. */
  appointmentsOn: (clinicId: string, day: string) =>
    api.get<Page<Appointment>>(`/clinics/${clinicId}/appointments`, { date: day, limit: 100 }),
};
