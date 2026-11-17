"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Spinner, StatusBadge } from "@/components/ui/feedback";
import { errorMessage } from "@/hooks/queries";
import { useCheckIn, useDayAppointments } from "@/hooks/staff";
import { formatTime } from "@/lib/format";
import { checkInCandidates } from "@/lib/queue-actions";

/** Booked patients arriving today. Checking in creates their queue token. */
export function CheckInPanel({ clinicId, day, timeZone, queuedAppointmentIds, live }: {
  clinicId: string; day: string; timeZone: string; queuedAppointmentIds: Set<string>; live: boolean;
}) {
  const appts = useDayAppointments(clinicId, day, true, live);
  const checkIn = useCheckIn(clinicId);
  const items = checkInCandidates(appts.data?.items ?? [], queuedAppointmentIds);

  return (
    <Card>
      <h2 className="font-display text-xl font-semibold text-ink">Check in booked patients</h2>
      <p className="text-sm text-slate-600">Today&apos;s appointments that have not arrived yet.</p>
      {appts.isLoading && <div className="mt-3"><Spinner /></div>}
      {appts.isError && <Alert tone="error" className="mt-3">{errorMessage(appts.error)}</Alert>}
      {checkIn.isError && <Alert tone="error" className="mt-3">{errorMessage(checkIn.error)}</Alert>}
      {appts.data && items.length === 0 && <p className="mt-3 text-sm text-slate-500">Nobody is waiting to be checked in.</p>}
      <ul className="mt-2 divide-y divide-slate-100">
        {items.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div>
              <p className="font-medium">{a.patient_name}</p>
              <p className="text-sm text-slate-600">
                {formatTime(a.starts_at, timeZone)} with {a.doctor_name} <StatusBadge status={a.status} />
              </p>
            </div>
            <Button
              size="sm" disabled={checkIn.isPending}
              loading={checkIn.isPending && checkIn.variables === a.id}
              onClick={() => checkIn.mutate(a.id)}
            >
              Check in
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
