"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { keys } from "@/hooks/queries";
import { platformService } from "@/services/platform";
import type { ClinicStatus } from "@/types/api";

const k = {
  clinics: ["platform-clinics"] as const,
  audit: ["platform-audit"] as const,
};

/** Every clinic (up to the API's limit of 200). The page filters by status itself so the counts stay accurate. */
export const usePlatformClinics = (enabled: boolean) =>
  useQuery({ queryKey: k.clinics, queryFn: () => platformService.clinics(), enabled });

export const usePlatformAudit = (enabled: boolean) =>
  useQuery({ queryKey: k.audit, queryFn: () => platformService.audit(100), enabled });

/** After a status change, refresh the platform lists and the patient-facing clinic directory (only open clinics appear there). */
export function useSetClinicStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { clinicId: string; status: ClinicStatus }) => platformService.setStatus(v.clinicId, v.status),
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: k.clinics }),
      qc.invalidateQueries({ queryKey: k.audit }),
      qc.invalidateQueries({ queryKey: keys.directory }),
    ]),
  });
}
