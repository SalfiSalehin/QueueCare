// Types mirror backend/app/schemas/*. Keep them in sync when the API changes.

export type ClinicRole = "CLINIC_ADMIN" | "RECEPTIONIST" | "DOCTOR" | "PATIENT";

export interface User {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  email_verified: boolean;
  platform_role: string;
}
export interface Membership { clinic_id: string; role: ClinicRole }
export interface MeResponse { user: User; memberships: Membership[]; csrf_token: string | null }
export interface AuthResponse { user: User; csrf_token: string }

export interface Page<T> { items: T[]; total: number; limit: number; offset: number }

export interface ClinicSummary {
  id: string; name: string; slug: string; status: string; timezone: string; created_at: string;
}

export type ClinicStatus = "PENDING" | "ACTIVE" | "SUSPENDED";
/** One row of the platform audit log. The API returns ids only, so clinic names are looked up from the clinic list. */
export interface PlatformAuditEntry { id: string; action: string; actor_user_id: string | null; clinic_id: string | null; created_at: string }

export type QueuePolicy = "APPOINTMENT_FIRST" | "FIFO";
export interface ClinicSettings {
  booking_horizon_days: number; min_notice_minutes: number; cancellation_cutoff_hours: number;
  queue_policy: QueuePolicy; walkin_priority_enabled: boolean;
}
export interface ClinicDetail extends ClinicSummary { settings: ClinicSettings }
/** Fields the clinic-update endpoint accepts. Only what changed is sent; the API merges settings. */
export interface ClinicPatch { name?: string; timezone?: string; settings?: Partial<ClinicSettings> }
export interface DoctorPatch { display_name?: string; department_id?: string; default_slot_minutes?: number; buffer_minutes?: number }

export type DoctorStatus = "AVAILABLE" | "BUSY" | "DELAYED" | "OFF_DUTY";
export interface Doctor {
  id: string; department_id: string; display_name: string; default_slot_minutes: number; buffer_minutes: number;
  status: DoctorStatus; current_delay_minutes: number; is_active: boolean; has_account: boolean;
}

export interface Slot { starts_at: string; ends_at: string; starts_at_local: string }
export interface DoctorAvailability {
  doctor_id: string; display_name: string; department_id: string; same_department: boolean;
  earliest: Slot | null; slots_in_range: number;
}
export interface Alternatives { requested: DoctorAvailability; alternatives: DoctorAvailability[] }

export type AppointmentStatus =
  | "PENDING" | "CONFIRMED" | "CHECKED_IN" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED" | "NO_SHOW";
export interface Appointment {
  id: string; doctor_id: string; doctor_name: string; patient_id: string; patient_name: string;
  starts_at: string; ends_at: string; starts_at_local: string; status: AppointmentStatus;
  rescheduled_from: string | null; cancel_reason: string | null;
}

export type QueueStatus =
  | "WAITING" | "CALLED" | "IN_CONSULTATION" | "COMPLETED" | "SKIPPED" | "CANCELLED" | "NO_SHOW";
export interface MyToken {
  id: string; token_label: string; doctor_id: string; doctor_name: string; status: QueueStatus;
  source: string; queue_date: string; people_ahead: number | null;
}
export interface EstimateFactor { feature: string; label: string; minutes: number }
export interface Estimate {
  token_id: string; status: string; source: "model" | "heuristic" | "not_waiting";
  median_minutes: number | null; lower_minutes: number | null; upper_minutes: number | null;
  model_version: string | null; note: string;
  /** Staff and doctors only. */
  factors?: EstimateFactor[] | null; typical_minutes?: number | null;
}

// ---- Analytics (clinic admins only)
export interface DateRange { start: string; end: string; timezone: string }
export interface Distribution { n: number; mean: number | null; p50: number | null; p90: number | null; max: number | null }
export interface DayPoint { date: string; appointments: number; arrivals: number; consultations: number }
export interface Overview {
  range: DateRange; appointments_total: number; appointments_by_status: Record<string, number>;
  no_show_rate: number | null; cancellation_rate: number | null; tokens_total: number;
  tokens_by_status: Record<string, number>; walk_in_share: number | null;
  wait_minutes: Distribution; consultation_minutes: Distribution; daily: DayPoint[];
}
export interface DoctorUtilisation {
  doctor_id: string; display_name: string; scheduled_minutes: number; booked_minutes: number;
  consultation_minutes: number; patients_seen: number; avg_wait_minutes: number | null;
  booked_utilisation: number | null; busy_utilisation: number | null;
}
export interface DoctorUtilisationOut { range: DateRange; items: DoctorUtilisation[] }
export interface HourLoad { hour: number; arrivals: number; avg_wait_minutes: number | null }
export interface WeekdayLoad { weekday: number; arrivals: number }
export interface Load { range: DateRange; by_hour: HourLoad[]; by_weekday: WeekdayLoad[] }
export interface VersionAccuracy {
  model_version: string; n: number; mae_minutes: number | null; median_abs_error_minutes: number | null;
  bias_minutes: number | null; interval_coverage: number | null; naive_baseline_mae_minutes: number | null;
}
export interface PredictionAccuracy { range: DateRange; versions: VersionAccuracy[]; enough_data: boolean; note: string }
export interface FeatureDrift { feature: string; label: string; psi: number; status: "stable" | "moderate" | "high" | string }
export interface PerformanceDrift {
  n: number; recent_mae_minutes: number | null; reference_mae_minutes: number | null; status: string;
}
export interface Drift {
  status: string; model_version: string | null; window_days: number; samples: number; overall: string | null;
  features: FeatureDrift[]; performance: PerformanceDrift | null; note: string;
}
export interface SlotSuggestion {
  doctor_id: string; display_name: string; status: "insufficient_data" | "keep" | "lengthen" | "shorten" | string;
  consultations: number; current_slot_minutes: number; suggested_slot_minutes: number | null;
  median_minutes: number | null; p80_minutes: number | null; overrun_share_now: number | null;
  overrun_share_suggested: number | null; advice: string;
}
export interface SlotSuggestions { window_days: number; items: SlotSuggestion[]; note: string }

// ---- Simulation lab
export interface Scenario {
  name: string; doctors: number; days: number; mean_service_minutes: number; slot_minutes: number;
  booked_share: number; walk_in_per_hour: number; seed: number;
}
export interface Outcome {
  visits: number; mean_wait_minutes: number; median_wait_minutes: number; p90_wait_minutes: number;
  share_waiting_over_30_min: number; mean_consultation_minutes: number; utilisation: number;
  overtime_day_share: number; mean_overtime_minutes: number;
}
export interface ScenarioResult {
  scenario: Scenario; outcome: Outcome; mean_wait_change_minutes: number | null;
  p90_wait_change_minutes: number | null; utilisation_change: number | null;
}
export interface SimulationResult { synthetic: boolean; results: ScenarioResult[]; note: string }

export interface QueueToken {
  id: string; token_label: string; doctor_id: string; patient_id: string; patient_name: string;
  appointment_id: string | null; source: string; status: QueueStatus; priority: number; queue_date: string;
  arrived_at: string; called_at: string | null; started_at: string | null; completed_at: string | null;
  position: number | null; version: number;
}
export interface QueueBoard {
  doctor_id: string; doctor_name: string; doctor_status: DoctorStatus; queue_date: string; policy: string;
  serving: QueueToken[]; waiting: QueueToken[]; skipped: QueueToken[]; finished_today: number;
}
export type QueueAction = "call" | "start" | "complete" | "skip" | "requeue" | "no-show" | "cancel";

export interface Patient { id: string; full_name: string; phone: string | null; date_of_birth: string | null; has_account: boolean }

export interface Ticket { ticket: string; expires_in: number; websocket_path: string }

/** Messages the server may send over the WebSocket. */
export type RealtimeMessage =
  | { type: "ready" }
  | { type: "pong" }
  | { type: "resync" }
  | { type: "event"; id: string; event: string; version: number; ts: string; data: Record<string, unknown> };

export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string; details?: Record<string, string>[] };
}

// ---- clinic setup (admin) ----
export interface Department { id: string; name: string; queue_prefix: string }
export interface Schedule {
  id: string; doctor_id: string; day_of_week: number; start_time: string; end_time: string;
  valid_from: string | null; valid_to: string | null;
}
export interface TimeOff { id: string; doctor_id: string; starts_at: string; ends_at: string; reason: string | null }
export interface Member { membership_id: string; user_id: string; full_name: string; email: string; role: ClinicRole; is_active: boolean }
export interface NewDoctor {
  display_name: string; department_id: string; default_slot_minutes: number; buffer_minutes: number; user_id?: string | null;
}
