import { api } from "@/lib/api";
import type { Estimate, MyToken, QueueAction, QueueBoard, QueueToken, Ticket } from "@/types/api";

export const queueService = {
  mine: (clinicId: string) => api.get<MyToken[]>(`/clinics/${clinicId}/queue/mine`),
  estimate: (clinicId: string, tokenId: string) =>
    api.get<Estimate>(`/clinics/${clinicId}/queue/tokens/${tokenId}/estimate`),
  board: (clinicId: string, doctorId: string) => api.get<QueueBoard>(`/clinics/${clinicId}/doctors/${doctorId}/queue`),
  callNext: (clinicId: string, doctorId: string) =>
    api.post<QueueToken>(`/clinics/${clinicId}/doctors/${doctorId}/queue/call-next`),
  act: (clinicId: string, tokenId: string, action: QueueAction) =>
    api.post<QueueToken>(`/clinics/${clinicId}/queue/tokens/${tokenId}/${action}`),
  checkIn: (clinicId: string, appointmentId: string) =>
    api.post<QueueToken>(`/clinics/${clinicId}/appointments/${appointmentId}/check-in`),
  walkIn: (clinicId: string, doctorId: string, patientId: string) =>
    api.post<QueueToken>(`/clinics/${clinicId}/queue/walk-ins`, { doctor_id: doctorId, patient_id: patientId }),
  ticket: (clinicId: string) => api.post<Ticket>(`/clinics/${clinicId}/realtime/ticket`),
};
