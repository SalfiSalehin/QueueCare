"use client";

import { useSuggestions } from "@/hooks/admin";
import { mins, pct, suggestionTone } from "@/lib/insights";
import { Panel, QueryBoundary, ToneBadge, words } from "./shared";

export function SlotAdviceTab({ clinicId }: { clinicId: string }) {
  const q = useSuggestions(clinicId, 90);
  const d = q.data;
  return (
    <QueryBoundary isLoading={q.isLoading} error={q.error}>
      {d && (
        <Panel title="Slot length advice" subtitle={`From completed consultations in the last ${d.window_days} days. This is advice only: nothing is changed for you.`}>
          {d.items.length === 0 ? (
            <p className="text-sm text-slate-500">No doctors to advise on yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {d.items.map((s) => (
                <li key={s.doctor_id} className="py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-display text-lg font-semibold text-ink">{s.display_name}</h3>
                    <ToneBadge tone={suggestionTone(s.status)}>{words(s.status)}</ToneBadge>
                  </div>
                  <p className="mt-1 text-sm text-slate-700">{s.advice}</p>
                  <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                    <Fact label="Consultations" value={String(s.consultations)} />
                    <Fact label="Slot now" value={`${s.current_slot_minutes} min`} />
                    <Fact label="Typical visit" value={mins(s.median_minutes, 1)} />
                    <Fact label="Suggested slot" value={s.suggested_slot_minutes ? `${s.suggested_slot_minutes} min` : "–"} />
                    <Fact label="Visits that overrun now" value={pct(s.overrun_share_now)} />
                    <Fact label="Overrun at suggestion" value={pct(s.overrun_share_suggested)} />
                  </dl>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-4 text-xs text-slate-500">{d.note}</p>
        </Panel>
      )}
    </QueryBoundary>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="tnum font-medium text-slate-900">{value}</dd>
    </div>
  );
}
