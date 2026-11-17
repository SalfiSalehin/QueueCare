import { api } from "@/lib/api";
import type {
  Drift, DoctorUtilisationOut, Load, Overview, PredictionAccuracy, Scenario, SimulationResult, SlotSuggestions,
} from "@/types/api";

type Range = { start: string; end: string };
const q = (r: Range) => ({ start_date: r.start, end_date: r.end });

export const analyticsService = {
  overview: (clinicId: string, r: Range) => api.get<Overview>(`/clinics/${clinicId}/analytics/overview`, q(r)),
  doctors: (clinicId: string, r: Range) => api.get<DoctorUtilisationOut>(`/clinics/${clinicId}/analytics/doctors`, q(r)),
  load: (clinicId: string, r: Range) => api.get<Load>(`/clinics/${clinicId}/analytics/load`, q(r)),
  accuracy: (clinicId: string, r: Range) =>
    api.get<PredictionAccuracy>(`/clinics/${clinicId}/analytics/prediction-accuracy`, q(r)),
  drift: (clinicId: string, days: number) => api.get<Drift>(`/clinics/${clinicId}/analytics/drift`, { days }),
  suggestions: (clinicId: string, days: number) =>
    api.get<SlotSuggestions>(`/clinics/${clinicId}/analytics/scheduling-suggestions`, { days }),
  simulate: (clinicId: string, scenarios: Scenario[]) =>
    api.post<SimulationResult>(`/clinics/${clinicId}/simulation`, { scenarios }),
};
