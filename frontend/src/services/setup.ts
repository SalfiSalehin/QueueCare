import { api } from "@/lib/api";
import type { ClinicRole, Department, Doctor, Member, NewDoctor, Page, Schedule, TimeOff } from "@/types/api";

const c = (id: string) => `/clinics/${id}`;

/** Clinic setup. Every write here is refused by the API unless the signed-in user is a CLINIC_ADMIN of that clinic. */
export const setupService = {
  departments: (id: string) => api.get<Page<Department>>(`${c(id)}/departments`, { limit: 100 }),
  createDepartment: (id: string, name: string, queuePrefix: string) =>
    api.post<Department>(`${c(id)}/departments`, { name, queue_prefix: queuePrefix }),
  renameDepartment: (id: string, departmentId: string, name: string) =>
    api.patch<Department>(`${c(id)}/departments/${departmentId}`, { name }),

  doctors: (id: string) => api.get<Page<Doctor>>(`${c(id)}/doctors`, { limit: 100, include_inactive: true }),
  createDoctor: (id: string, body: NewDoctor) => api.post<Doctor>(`${c(id)}/doctors`, body),
  setDoctorActive: (id: string, doctorId: string, isActive: boolean) =>
    api.patch<Doctor>(`${c(id)}/doctors/${doctorId}`, { is_active: isActive }),

  schedules: (id: string, doctorId: string) => api.get<Schedule[]>(`${c(id)}/doctors/${doctorId}/schedules`),
  addSchedule: (id: string, doctorId: string, day: number, start: string, end: string) =>
    api.post<Schedule>(`${c(id)}/doctors/${doctorId}/schedules`, {
      day_of_week: day, start_time: `${start}:00`, end_time: `${end}:00`,
    }),
  deleteSchedule: (id: string, doctorId: string, scheduleId: string) =>
    api.del<void>(`${c(id)}/doctors/${doctorId}/schedules/${scheduleId}`),

  timeOff: (id: string, doctorId: string) => api.get<TimeOff[]>(`${c(id)}/doctors/${doctorId}/time-off`),
  addTimeOff: (id: string, doctorId: string, startsAtUtc: string, endsAtUtc: string, reason: string | null) =>
    api.post<TimeOff>(`${c(id)}/doctors/${doctorId}/time-off`, { starts_at: startsAtUtc, ends_at: endsAtUtc, reason }),
  deleteTimeOff: (id: string, doctorId: string, timeOffId: string) =>
    api.del<void>(`${c(id)}/doctors/${doctorId}/time-off/${timeOffId}`),

  members: (id: string) => api.get<Member[]>(`${c(id)}/members`),
  addMember: (id: string, email: string, role: ClinicRole) => api.post<Member>(`${c(id)}/members`, { email, role }),
  setMemberActive: (id: string, membershipId: string, isActive: boolean) =>
    api.patch<Member>(`${c(id)}/members/${membershipId}`, { is_active: isActive }),
};
