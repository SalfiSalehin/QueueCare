"use client";

import { Alert } from "@/components/ui/feedback";
import { useAccuracy, useDrift } from "@/hooks/admin";
import { driftTone, mins, pct, signed } from "@/lib/insights";
import { Panel, QueryBoundary, ToneBadge, words } from "./shared";

export function ModelHealthTab({ clinicId, range }: { clinicId: string; range: { start: string; end: string } }) {
  const drift = useDrift(clinicId, 14);
  const acc = useAccuracy(clinicId, range);
  const d = drift.data;
  const perf = d?.performance;

  return (
    <div className="space-y-6">
      <Alert tone="info">
        These screens check the wait-time model against this clinic&apos;s own recent data. A warning is a reason to look,
        not proof the model is wrong. The model was trained on simulated data.
      </Alert>

      <Panel title="Has the data changed?" subtitle="Compares what the model sees now with what it was trained on (PSI: under 0.1 stable, 0.1 to 0.25 moderate, over 0.25 high).">
        <QueryBoundary isLoading={drift.isLoading} error={drift.error}>
          {d && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-3">
                <ToneBadge tone={d.status === "ok" ? driftTone(d.overall ?? "ok") : "neutral"}>
                  {d.status === "ok" ? `overall: ${d.overall ?? "ok"}` : words(d.status)}
                </ToneBadge>
                <span className="text-sm text-slate-600">
                  {d.model_version ? `Model ${d.model_version}` : "No trained model is active"}, last {d.window_days} days, {d.samples} predictions compared
                </span>
              </div>
              <p className="text-sm text-slate-600">{d.note}</p>
              {d.features.length > 0 && (
                <ul className="divide-y divide-slate-100">
                  {d.features.map((f) => (
                    <li key={f.feature} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                      <span>{f.label}</span>
                      <span className="flex items-center gap-3">
                        <span className="tnum text-slate-500">PSI {f.psi.toFixed(2)}</span>
                        <ToneBadge tone={driftTone(f.status)}>{f.status}</ToneBadge>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {perf && (
                <div className="rounded-2xl bg-slate-50 p-4 text-sm">
                  <p className="font-medium text-slate-800">Accuracy now compared with training time <ToneBadge tone={driftTone(perf.status)}>{words(perf.status)}</ToneBadge></p>
                  <p className="mt-2 text-slate-600">
                    Recent average error {mins(perf.recent_mae_minutes, 1)} over {perf.n} predictions; at training time (simulated test data) {mins(perf.reference_mae_minutes, 1)}.
                  </p>
                </div>
              )}
            </div>
          )}
        </QueryBoundary>
      </Panel>

      <Panel title="How accurate have the estimates been?" subtitle="Each prediction compared with the wait that actually happened.">
        <QueryBoundary isLoading={acc.isLoading} error={acc.error}>
          {acc.data && (
            <div className="space-y-4">
              {!acc.data.enough_data && <Alert tone="warning">Fewer than 30 finished predictions in this range. Do not read much into these numbers yet.</Alert>}
              {acc.data.versions.length === 0 ? (
                <p className="text-sm text-slate-500">No predictions have been compared with real waits yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[40rem] text-left text-sm">
                    <thead className="text-xs text-slate-500">
                      <tr>
                        <th scope="col" className="py-2 pr-4 font-medium">Model version</th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">Predictions</th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">Average error</th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">Simple rule&apos;s error</th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">Bias</th>
                        <th scope="col" className="py-2 pl-3 text-right font-medium">Actual inside range</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {acc.data.versions.map((v) => (
                        <tr key={v.model_version}>
                          <th scope="row" className="py-3 pr-4 font-medium">{v.model_version}</th>
                          <td className="tnum px-3 py-3 text-right">{v.n}</td>
                          <td className="tnum px-3 py-3 text-right">{mins(v.mae_minutes, 1)}</td>
                          <td className="tnum px-3 py-3 text-right">{mins(v.naive_baseline_mae_minutes, 1)}</td>
                          <td className="tnum px-3 py-3 text-right">{signed(v.bias_minutes, " min")}</td>
                          <td className="tnum py-3 pl-3 text-right">{pct(v.interval_coverage)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="text-xs leading-relaxed text-slate-500">{acc.data.note} Bias below zero means the model under-predicts waits.</p>
            </div>
          )}
        </QueryBoundary>
      </Panel>
    </div>
  );
}
