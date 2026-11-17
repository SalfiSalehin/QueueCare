"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { analyticsService } from "@/services/analytics";
import type { Scenario } from "@/types/api";

interface Range { start: string; end: string }

// Analytics are not live data: no polling. Stale for a minute so switching tabs does not refetch (the API is rate limited).
const opts = { staleTime: 60_000, retry: false } as const;

export const useOverview = (id: string, r: Range, enabled = true) =>
  useQuery({ queryKey: ["an-overview", id, r], queryFn: () => analyticsService.overview(id, r), enabled, ...opts });
export const useDoctorStats = (id: string, r: Range, enabled = true) =>
  useQuery({ queryKey: ["an-doctors", id, r], queryFn: () => analyticsService.doctors(id, r), enabled, ...opts });
export const useLoad = (id: string, r: Range, enabled = true) =>
  useQuery({ queryKey: ["an-load", id, r], queryFn: () => analyticsService.load(id, r), enabled, ...opts });
export const useAccuracy = (id: string, r: Range, enabled = true) =>
  useQuery({ queryKey: ["an-accuracy", id, r], queryFn: () => analyticsService.accuracy(id, r), enabled, ...opts });
export const useDrift = (id: string, days: number, enabled = true) =>
  useQuery({ queryKey: ["an-drift", id, days], queryFn: () => analyticsService.drift(id, days), enabled, ...opts });
export const useSuggestions = (id: string, days: number, enabled = true) =>
  useQuery({ queryKey: ["an-suggest", id, days], queryFn: () => analyticsService.suggestions(id, days), enabled, ...opts });

export const useSimulation = (id: string) =>
  useMutation({ mutationFn: (scenarios: Scenario[]) => analyticsService.simulate(id, scenarios) });
