"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { appointmentService } from "@/services/appointments";
import { authService } from "@/services/auth";
import { clinicService } from "@/services/clinics";
import { queueService } from "@/services/queue";

export const keys = {
  me: ["me"] as const,
  directory: ["clinics"] as const,
  clinic: (id: string) => ["clinic", id] as const,
  doctors: (id: string) => ["doctors", id] as const,
  slots: (id: string, doctorId: string) => ["slots", id, doctorId] as const,
  alternatives: (id: string, doctorId: string) => ["alternatives", id, doctorId] as const,
  appointments: (id: string) => ["appointments", id] as const,
  myQueue: (id: string) => ["my-queue", id] as const,
  estimate: (id: string, tokenId: string) => ["estimate", id, tokenId] as const,
};

export const useMe = () =>
  useQuery({ queryKey: keys.me, queryFn: authService.me, staleTime: 60_000, retry: false });

/** Open clinics. With no arguments it is the whole directory (up to 100), as the dashboard uses it. Searches share the "clinics" key
 *  prefix, so a status change that invalidates the directory refreshes them too. */
export const useDirectory = (q = "", limit = 100) =>
  useQuery({
    queryKey: [...keys.directory, { q, limit }] as const,
    queryFn: () => clinicService.directory(q, limit),
    placeholderData: keepPreviousData,          // keep the old list on screen while the next search loads, so it does not flash
  });

export const useClinic = (clinicId: string) =>
  useQuery({ queryKey: keys.clinic(clinicId), queryFn: () => clinicService.get(clinicId) });

export const useDoctors = (clinicId: string) =>
  useQuery({ queryKey: keys.doctors(clinicId), queryFn: () => clinicService.doctors(clinicId) });

export const useSlots = (clinicId: string, doctorId: string | null) =>
  useQuery({
    queryKey: keys.slots(clinicId, doctorId ?? ""),
    queryFn: () => appointmentService.slots(clinicId, doctorId as string),
    enabled: doctorId !== null,
  });

export const useAlternatives = (clinicId: string, doctorId: string | null, enabled: boolean) =>
  useQuery({
    queryKey: keys.alternatives(clinicId, doctorId ?? ""),
    queryFn: () => appointmentService.alternatives(clinicId, doctorId as string),
    enabled: enabled && doctorId !== null,
  });

export const useAppointments = (clinicId: string) =>
  useQuery({ queryKey: keys.appointments(clinicId), queryFn: () => appointmentService.list(clinicId) });

/** Polls every 5 s. (Push updates over WebSocket arrive with the staff slice; polling is the honest fallback.) */
export const useMyQueue = (clinicId: string) =>
  useQuery({ queryKey: keys.myQueue(clinicId), queryFn: () => queueService.mine(clinicId), refetchInterval: 5_000 });

export const useEstimate = (clinicId: string, tokenId: string, enabled: boolean) =>
  useQuery({
    queryKey: keys.estimate(clinicId, tokenId),
    queryFn: () => queueService.estimate(clinicId, tokenId),
    enabled,
    refetchInterval: 15_000,
  });

export function useJoinClinic() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clinicId: string) => clinicService.join(clinicId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.me }),
  });
}

export function useBook(clinicId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ doctorId, startsAt }: { doctorId: string; startsAt: string }) =>
      appointmentService.book(clinicId, doctorId, startsAt),
    onSettled: (_data, _err, vars) => {
      void qc.invalidateQueries({ queryKey: keys.slots(clinicId, vars.doctorId) });
      void qc.invalidateQueries({ queryKey: keys.appointments(clinicId) });
    },
  });
}

export function useCancel(clinicId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (appointmentId: string) => appointmentService.cancel(clinicId, appointmentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.appointments(clinicId) }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authService.logout,
    onSettled: () => qc.clear(),
  });
}

export const errorMessage = (e: unknown): string =>
  e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
