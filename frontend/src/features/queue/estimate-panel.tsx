"use client";

import { Alert, Spinner } from "@/components/ui/feedback";
import { errorMessage, useEstimate } from "@/hooks/queries";
import { mins, signed } from "@/lib/insights";

/** Staff-only explanation of one wait estimate: the range, and what moved it up or down from the model's typical value. */
export function EstimatePanel({ clinicId, tokenId }: { clinicId: string; tokenId: string }) {
  const q = useEstimate(clinicId, tokenId, true);
  if (q.isLoading) return <Spinner label="Loading the estimate" />;
  if (q.isError) return <Alert tone="error">{errorMessage(q.error)}</Alert>;
  const e = q.data;
  if (!e) return null;
  const factors = e.factors ?? [];
  const biggest = Math.max(1, ...factors.map((f) => Math.abs(f.minutes)));

  return (
    <div className="mt-3 rounded-2xl bg-slate-50 p-4 text-sm">
      <p className="font-medium text-slate-900">
        About {mins(e.median_minutes)}
        {e.lower_minutes !== null && e.upper_minutes !== null && <span className="font-normal text-slate-600"> (likely {mins(e.lower_minutes)} to {mins(e.upper_minutes)})</span>}
      </p>
      <p className="mt-1 text-xs text-slate-600">
        {e.source === "model" ? `From model ${e.model_version ?? ""}, trained on simulated data.` : "From a simple rule (people ahead times the doctor's recent average), not a model."}
      </p>
      {factors.length > 0 ? (
        <>
          <p className="mt-3 text-xs font-medium text-slate-700">
            What moved it{e.typical_minutes != null ? ` (typical is ${mins(e.typical_minutes)})` : ""}
          </p>
          <ul className="mt-2 space-y-1.5">
            {factors.map((f) => (
              <li key={f.feature} className="grid grid-cols-[1fr_6rem_3.5rem] items-center gap-2 text-xs">
                <span className="truncate text-slate-700">{f.label}</span>
                <span aria-hidden className="h-2 overflow-hidden rounded-full bg-slate-200">
                  <span className={f.minutes >= 0 ? "block h-full bg-amber-400" : "block h-full bg-teal-500"} style={{ width: `${Math.max(4, Math.round((Math.abs(f.minutes) / biggest) * 100))}%` }} />
                </span>
                <span className="tnum text-right font-medium">{signed(f.minutes, " min")}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">Amber pushed the estimate up, green pushed it down. These show what the model used, not why a patient is slow.</p>
        </>
      ) : (
        <p className="mt-2 text-xs text-slate-500">No breakdown is available for a simple-rule estimate.</p>
      )}
    </div>
  );
}
