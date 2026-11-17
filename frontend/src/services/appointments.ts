import { api } from "@/lib/api";
import type { Alternatives, Appointment, Page, Slot } from "@/types/api";

export const appointmentService = {
  slots: (clinicId: string, doctorId: string) => api.get<Slot[]>(`/clinics/${clinicId}/doctors/${doctorId}/slots`),
  alternatives: (clinicId: string, doctorId: string) =>
    api.get<Alternatives>(`/clinics/${clinicId}/doctors/${doctorId}/alternatives`),
  list: (clinicId: string) => api.get<Page<Appointment>>(`/clinics/${clinicId}/appointments`, { limit: 50 }),
  book: (clinicId: string, doctorId: string, startsAt: string) =>
    api.post<Appointment>(`/clinics/${clinicId}/appointments`, { doctor_id: doctorId, starts_at: startsAt }),
  cancel: (clinicId: string, appointmentId: string) =>
    api.post<Appointment>(`/clinics/${clinicId}/appointments/${appointmentId}/cancel`, {}),
};
