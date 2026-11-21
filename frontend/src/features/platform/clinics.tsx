"use client";

import { useState } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { errorMessage } from "@/hooks/queries";
import { usePlatformClinics, useSetClinicStatus } from "@/hooks/platform";
import { cn } from "@/lib/cn";
import { formatDateTime, plural } from "@/lib/format";
import { clinicActions, confirmMessage, countByStatus, filterClinics, statusLabel, STATUS_FILTERS, type StatusAction, type StatusFilter } from "@/lib/platform";

const TONE: Record<string, string> = {
  PENDING: "bg-amber-100 text-amber-900", ACTIVE: "bg-emerald-100 text-emerald-900", SUSPENDED: "bg-slate-200 text-slate-700",
};

export function ClinicsSection() {
  const clinics = usePlatformClinics(true);
  const setStatus = useSetClinicStatus();
  const [filter, setFilter] = useState<StatusFilter>("PENDING");
  const [confirming, setConfirming] = useState<{ id: string; action: StatusAction } | null>(null);

  const all = clinics.data ?? [];
  const counts = countByStatus(all);
  const shown = filterClinics(all, filter);

  const apply = (clinicId: string, action: StatusAction) => {
    setConfirming(null);
    setStatus.mutate({ clinicId, status: action.to });
  };

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Clinic status" className="flex w-full gap-1 overflow-x-auto whitespace-nowrap rounded-2xl bg-white p-1 shadow-xs ring-1 ring-slate-200 sm:inline-flex sm:w-auto">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.id} type="button" role="tab" aria-selected={filter === f.id} onClick={() => { setFilter(f.id); setConfirming(null); }}
            className={cn("rounded-xl px-4 py-2 text-sm font-medium transition-colors", filter === f.id ? "bg-ink text-white" : "text-slate-600 hover:bg-slate-100")}
          >
            {f.label} ({counts[f.id]})
          </button>
        ))}
      </div>

      {clinics.isLoading && <Spinner label="Loading clinics" />}
      {clinics.isError && <Alert tone="error">{errorMessage(clinics.error)}</Alert>}
      {setStatus.isError && <Alert tone="error">{errorMessage(setStatus.error)}</Alert>}
      {all.length >= 200 && <Alert tone="info">Showing the 200 most recent clinics. Older ones are not listed here.</Alert>}

      {clinics.data && shown.length === 0 && (
        <EmptyState title={filter === "PENDING" ? "No clinics are waiting for approval." : "No clinics here."}>
          {filter === "PENDING" ? "New clinics appear here as soon as someone registers one." : "Pick another status above to see the rest."}
        </EmptyState>
      )}

      <ul className="space-y-3">
        {shown.map((c) => {
          const asking = confirming?.id === c.id ? confirming.action : null;
          return (
            <li key={c.id} className="rounded-3xl bg-white p-4 shadow-xs ring-1 ring-slate-200/80 sm:p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <Avatar name={c.name} />
                  <div className="min-w-0">
                    <h2 className="truncate font-display text-lg font-semibold text-ink">{c.name}</h2>
                    <p className="text-xs text-slate-600">
                      {c.slug} · {c.timezone} · registered {formatDateTime(c.created_at, c.timezone)}
                    </p>
                  </div>
                </div>
                <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", TONE[c.status] ?? "bg-slate-200 text-slate-800")}>
                  <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />
                  {statusLabel(c.status)}
                </span>
              </div>

              {asking ? (
                <div className="mt-4 space-y-3">
                  <Alert tone="warning">{confirmMessage(c.name, asking)}</Alert>
                  <div className="flex gap-2">
                    <Button size="sm" variant="danger" aria-label={`Confirm ${asking.label} ${c.name}`} onClick={() => apply(c.id, asking)}>Yes, {asking.label.toLowerCase()}</Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <div className="mt-4 flex flex-wrap gap-2">
                  {clinicActions(c.status).map((a) => (
                    <Button
                      key={a.to} size="sm" variant={a.confirm ? "secondary" : "primary"} aria-label={`${a.label} ${c.name}`}
                      loading={setStatus.isPending && setStatus.variables?.clinicId === c.id}
                      onClick={() => (a.confirm ? setConfirming({ id: c.id, action: a }) : apply(c.id, a))}
                    >
                      {a.label}
                    </Button>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {clinics.data && <p className="text-xs text-slate-600">{plural(all.length, "clinic")} in total.</p>}
    </div>
  );
}
