"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { patientService } from "@/services/patients";
import { queueService } from "@/services/queue";
import type { Doctor, QueueAction } from "@/types/api";

const FAST_POLL = 5_000;      // while the live connection is down
const SLOW_POLL = 60_000;     // safety net while it is up

/** One queue board per doctor. A doctor's login can only read their own board (the API answers 404 for the
 *  others), so for the DOCTOR role the boards that fail with 404 are simply not "mine" and are hidden. */
export function useBoards(clinicId: string, doctors: Doctor[], live: boolean) {
  return useQueries({
    queries: doctors.map((d) => ({
      queryKey: ["board", clinicId, d.id] as const,
      queryFn: () => queueService.board(clinicId, d.id),
      retry: false,
      refetchInterval: live ? SLOW_POLL : FAST_POLL,
    })),
  });
}

export function useDayAppointments(clinicId: string, day: string, enabled: boolean, live: boolean) {
  return useQuery({
    queryKey: ["day-appointments", clinicId, day] as const,
    queryFn: () => patientService.appointmentsOn(clinicId, day),
    enabled,
    refetchInterval: live ? SLOW_POLL : FAST_POLL,
  });
}

function useRefreshQueue(clinicId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["board", clinicId] });
    void qc.invalidateQueries({ queryKey: ["day-appointments", clinicId] });
  };
}

export function useTokenAction(clinicId: string) {
  const refresh = useRefreshQueue(clinicId);
  return useMutation({
    mutationFn: ({ tokenId, action }: { tokenId: string; action: QueueAction }) =>
      queueService.act(clinicId, tokenId, action),
    onSettled: refresh,       // also on error: a 409 usually means the board was stale
  });
}

export function useCallNext(clinicId: string) {
  const refresh = useRefreshQueue(clinicId);
  return useMutation({ mutationFn: (doctorId: string) => queueService.callNext(clinicId, doctorId), onSettled: refresh });
}

export function useCheckIn(clinicId: string) {
  const refresh = useRefreshQueue(clinicId);
  return useMutation({ mutationFn: (appointmentId: string) => queueService.checkIn(clinicId, appointmentId), onSettled: refresh });
}

export function useWalkIn(clinicId: string) {
  const refresh = useRefreshQueue(clinicId);
  return useMutation({
    mutationFn: ({ doctorId, patientId }: { doctorId: string; patientId: string }) =>
      queueService.walkIn(clinicId, doctorId, patientId),
    onSettled: refresh,
  });
}

export function useCreatePatient(clinicId: string) {
  return useMutation({
    mutationFn: ({ fullName, phone }: { fullName: string; phone: string | null }) =>
      patientService.create(clinicId, fullName, phone),
  });
}

/** Debounced patient search (the API needs at least 2 characters). */
export function usePatientSearch(clinicId: string, text: string) {
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 300);
    return () => clearTimeout(t);
  }, [text]);
  return useQuery({
    queryKey: ["patients", clinicId, q] as const,
    queryFn: () => patientService.search(clinicId, q),
    enabled: q.length >= 2,
  });
}

