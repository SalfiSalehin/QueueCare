"use client";

import { useState } from "react";
import { useClinicCtx } from "@/components/clinic-context";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState, Spinner, StatusBadge } from "@/components/ui/feedback";
import { errorMessage, useAppointments, useCancel } from "@/hooks/queries";
import { dayOf, formatTime, monthOf } from "@/lib/format";

export default function AppointmentsPage() {
  const { clinicId, clinic } = useClinicCtx();
  const appts = useAppointments(clinicId);
  const cancel = useCancel(clinicId);
  const [confirming, setConfirming] = useState<string | null>(null);
  const items = [...(appts.data?.items ?? [])].sort((a, b) => (a.starts_at < b.starts_at ? 1 : -1));

  return (
    <div className="space-y-4">
      {appts.isLoading && <Spinner />}
      {appts.isError && <Alert tone="error">{errorMessage(appts.error)}</Alert>}
      {cancel.isError && <Alert tone="error">{errorMessage(cancel.error)}</Alert>}
      {appts.data && items.length === 0 && <EmptyState title="No appointments yet." />}
      <ul className="space-y-3">
        {items.map((a) => {
          const cancellable = (a.status === "PENDING" || a.status === "CONFIRMED") && new Date(a.starts_at) > new Date();
          return (
            <li key={a.id}>
              <div className="flex flex-wrap items-center justify-between gap-4 rounded-3xl bg-white p-4 shadow-sm ring-1 ring-slate-200/80">
                <div className="flex items-center gap-4">
                  <div className="grid h-16 w-16 shrink-0 place-items-center rounded-2xl bg-mint text-center leading-tight text-teal-950">
                    <span>
                      <span className="tnum block font-display text-2xl font-semibold">{dayOf(a.starts_at, clinic.timezone)}</span>
                      <span className="block text-xs">{monthOf(a.starts_at, clinic.timezone)}</span>
                    </span>
                  </div>
                  <div>
                    <p className="font-display text-lg font-semibold text-ink">{formatTime(a.starts_at, clinic.timezone)}</p>
                    <p className="text-sm text-slate-600">{a.doctor_name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge status={a.status} />
                  {cancellable && (confirming === a.id ? (
                    <span className="flex gap-2">
                      <Button size="sm" variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate(a.id, { onSettled: () => setConfirming(null) })}>Yes, cancel</Button>
                      <Button size="sm" variant="secondary" onClick={() => setConfirming(null)}>Keep</Button>
                    </span>
                  ) : (
                    <Button size="sm" variant="secondary" onClick={() => setConfirming(a.id)}>Cancel</Button>
                  ))}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
