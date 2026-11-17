"use client";

import { useClinicCtx } from "@/components/clinic-context";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { PageTitle, StatTile } from "@/components/ui/card";
import { CheckInPanel } from "@/features/queue/check-in-panel";
import { DoctorBoard } from "@/features/queue/doctor-board";
import { LiveBadge } from "@/features/queue/live-badge";
import { WalkInPanel } from "@/features/queue/walk-in-panel";
import { errorMessage, useDoctors } from "@/hooks/queries";
import { useRealtime } from "@/hooks/realtime";
import { useBoards } from "@/hooks/staff";
import { ApiError } from "@/lib/api";
import { localDay } from "@/lib/format";
import { isFrontDesk } from "@/lib/queue-actions";

export default function BoardPage() {
  const { clinicId, clinic, role } = useClinicCtx();
  const live = useRealtime(clinicId);
  const doctorsQ = useDoctors(clinicId);
  const doctors = (doctorsQ.data?.items ?? []).filter((d) => d.is_active);
  const boards = useBoards(clinicId, doctors, live === "live");
  const frontDesk = isFrontDesk(role);

  // For a doctor login the API only lets one board through; the others are 404 and are not shown.
  const visible = boards.flatMap((q) => (q.data ? [q.data] : []));
  const realErrors = boards.filter((q) => q.isError && !(role === "DOCTOR" && q.error instanceof ApiError && q.error.status === 404));
  const loading = doctorsQ.isLoading || boards.some((q) => q.isLoading);
  const today = localDay(new Date().toISOString(), clinic.timezone);
  const queuedAppointmentIds = new Set(
    visible.flatMap((b) => [...b.serving, ...b.waiting, ...b.skipped]).flatMap((t) => (t.appointment_id ? [t.appointment_id] : [])),
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageTitle title="Queue board" subtitle={frontDesk ? "Every doctor's queue for today." : "Your queue for today."} />
        <LiveBadge status={live} />
      </div>
      {visible.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile tone="dark" label="Waiting now" value={visible.reduce((n, b) => n + b.waiting.length, 0)} />
          <StatTile label="With a doctor" value={visible.reduce((n, b) => n + b.serving.length, 0)} />
          <StatTile label="Seen today" value={visible.reduce((n, b) => n + b.finished_today, 0)} />
        </div>
      )}
      {doctorsQ.isError && <Alert tone="error">{errorMessage(doctorsQ.error)}</Alert>}
      {realErrors.length > 0 && <Alert tone="error">Some queues could not be loaded: {errorMessage(realErrors[0]?.error)}</Alert>}
      {loading && <Spinner />}
      {!loading && visible.length === 0 && (
        <EmptyState title={role === "DOCTOR" ? "No doctor profile is linked to your login." : "No active doctors yet."}>
          {role === "DOCTOR" ? "Ask a clinic admin to link your account to a doctor profile." : role === "CLINIC_ADMIN" ? "Add a department, a doctor and their hours under Setup." : "Ask a clinic admin to add a doctor and their hours."}
        </EmptyState>
      )}
      <div className={frontDesk ? "grid gap-6 lg:grid-cols-[1fr_22rem]" : ""}>
        <div className="space-y-6">
          {visible.map((b) => <DoctorBoard key={b.doctor_id} clinicId={clinicId} board={b} role={role} timeZone={clinic.timezone} />)}
        </div>
        {frontDesk && (
          <div className="space-y-6">
            <CheckInPanel clinicId={clinicId} day={today} timeZone={clinic.timezone} queuedAppointmentIds={queuedAppointmentIds} live={live === "live"} />
            {doctors.length > 0 && <WalkInPanel clinicId={clinicId} doctors={doctors} />}
          </div>
        )}
      </div>
    </div>
  );
}
