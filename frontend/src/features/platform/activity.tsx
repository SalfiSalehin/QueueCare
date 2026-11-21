"use client";

import { useState } from "react";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { errorMessage } from "@/hooks/queries";
import { usePlatformAudit, usePlatformClinics } from "@/hooks/platform";
import { formatDateTime } from "@/lib/format";
import { auditLabel, filterAudit } from "@/lib/platform";

/**
 * Recent audit events. The API records the action, the clinic and the time, but not who did it by name or the old and
 * new status. By default only clinic changes are shown; sign-ins and account events are behind a switch.
 */
export function ActivitySection() {
  const [includeAll, setIncludeAll] = useState(false);
  const audit = usePlatformAudit(true);
  const clinics = usePlatformClinics(true);
  const shown = filterAudit(audit.data ?? [], includeAll);
  const byId = new Map((clinics.data ?? []).map((c) => [c.id, c] as const));

  return (
    <div className="space-y-4">
      {audit.isLoading && <Spinner label="Loading activity" />}
      {audit.isError && <Alert tone="error">{errorMessage(audit.error)}</Alert>}
      <label className="flex items-center gap-3 text-sm text-slate-800">
        <input type="checkbox" className="size-4" checked={includeAll} onChange={(e) => setIncludeAll(e.target.checked)} />
        <span>Include sign-ins and account events</span>
      </label>
      {audit.data && shown.length === 0 && (
        <EmptyState title="Nothing to show.">{includeAll ? "No events have been recorded yet." : "No clinic changes in the latest events. Include sign-ins to see everything."}</EmptyState>
      )}
      <ul className="divide-y divide-slate-200 rounded-3xl bg-white shadow-xs ring-1 ring-slate-200/80">
        {shown.map((e) => {
          const clinic = e.clinic_id ? byId.get(e.clinic_id) : undefined;
          return (
            <li key={e.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3 text-sm">
              <span>
                <span className="font-medium text-ink">{auditLabel(e.action)}</span>
                {e.clinic_id && <span className="text-slate-700"> · {clinic ? clinic.name : "a clinic that is no longer listed"}</span>}
              </span>
              <span className="text-xs text-slate-600">{formatDateTime(e.created_at, clinic?.timezone ?? "UTC")}{clinic ? "" : " UTC"}</span>
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-slate-600">Taken from the latest 200 events, newest first.</p>
    </div>
  );
}
