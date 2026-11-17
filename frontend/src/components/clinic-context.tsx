"use client";

import { createContext, useContext } from "react";
import type { ClinicRole, ClinicSummary } from "@/types/api";

export interface ClinicCtx { clinicId: string; clinic: ClinicSummary; role: ClinicRole }

export const ClinicContext = createContext<ClinicCtx | null>(null);

export function useClinicCtx(): ClinicCtx {
  const ctx = useContext(ClinicContext);
  if (!ctx) throw new Error("useClinicCtx must be used inside a clinic page");
  return ctx;
}
