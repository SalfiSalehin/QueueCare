"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { setupService } from "@/services/setup";
import type { ClinicRole, NewDoctor } from "@/types/api";

// Setup data changes only when an admin changes it. After a change, the lists the change touches are refetched; the
// patient-facing doctor list (["doctors", id]) is refreshed too so the booking page never shows a stale roster.
const k = {
  departments: (id: string) => ["setup-departments", id] as const,
  doctors: (id: string) => ["setup-doctors", id] as const,
  schedules: (id: string, d: string) => ["setup-schedules", id, d] as const,
  timeOff: (id: string, d: string) => ["setup-time-off", id, d] as const,
  members: (id: string) => ["setup-members", id] as const,
};

export const useDepartments = (id: string) => useQuery({ queryKey: k.departments(id), queryFn: () => setupService.departments(id) });
export const useAllDoctors = (id: string) => useQuery({ queryKey: k.doctors(id), queryFn: () => setupService.doctors(id) });
export const useSchedules = (id: string, doctorId: string) =>
  useQuery({ queryKey: k.schedules(id, doctorId), queryFn: () => setupService.schedules(id, doctorId) });
export const useTimeOff = (id: string, doctorId: string) =>
  useQuery({ queryKey: k.timeOff(id, doctorId), queryFn: () => setupService.timeOff(id, doctorId) });
export const useMembers = (id: string) => useQuery({ queryKey: k.members(id), queryFn: () => setupService.members(id) });

function useRefresh(id: string) {
  const qc = useQueryClient();
  return (...parts: (readonly unknown[])[]) => {
    for (const queryKey of parts) void qc.invalidateQueries({ queryKey });
    void qc.invalidateQueries({ queryKey: ["doctors", id] });
    void qc.invalidateQueries({ queryKey: ["board", id] });
  };
}

export function useCreateDepartment(id: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (v: { name: string; prefix: string }) => setupService.createDepartment(id, v.name.trim(), v.prefix.trim().toUpperCase()),
    onSuccess: () => refresh(k.departments(id)),
  });
}

export function useRenameDepartment(id: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (v: { departmentId: string; name: string }) => setupService.renameDepartment(id, v.departmentId, v.name.trim()),
    onSuccess: () => refresh(k.departments(id)),
  });
}

export function useCreateDoctor(id: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (body: NewDoctor) => setupService.createDoctor(id, body),
    onSuccess: () => refresh(k.doctors(id)),
  });
}

export function useSetDoctorActive(id: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (v: { doctorId: string; isActive: boolean }) => setupService.setDoctorActive(id, v.doctorId, v.isActive),
    onSuccess: () => refresh(k.doctors(id)),
  });
}

export function useAddSchedule(id: string, doctorId: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (v: { day: number; start: string; end: string }) => setupService.addSchedule(id, doctorId, v.day, v.start, v.end),
    onSuccess: () => refresh(k.schedules(id, doctorId)),
  });
}

export function useDeleteSchedule(id: string, doctorId: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (scheduleId: string) => setupService.deleteSchedule(id, doctorId, scheduleId),
    onSuccess: () => refresh(k.schedules(id, doctorId)),
  });
}

export function useAddTimeOff(id: string, doctorId: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (v: { startsAtUtc: string; endsAtUtc: string; reason: string | null }) =>
      setupService.addTimeOff(id, doctorId, v.startsAtUtc, v.endsAtUtc, v.reason),
    onSuccess: () => refresh(k.timeOff(id, doctorId)),
  });
}

export function useDeleteTimeOff(id: string, doctorId: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (timeOffId: string) => setupService.deleteTimeOff(id, doctorId, timeOffId),
    onSuccess: () => refresh(k.timeOff(id, doctorId)),
  });
}

export function useAddMember(id: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (v: { email: string; role: ClinicRole }) => setupService.addMember(id, v.email.trim().toLowerCase(), v.role),
    onSuccess: () => refresh(k.members(id)),
  });
}

export function useSetMemberActive(id: string) {
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: (v: { membershipId: string; isActive: boolean }) => setupService.setMemberActive(id, v.membershipId, v.isActive),
    onSuccess: () => refresh(k.members(id)),
  });
}
