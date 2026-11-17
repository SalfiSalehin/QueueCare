"use client";

import { useState } from "react";
import { useClinicCtx } from "@/components/clinic-context";
import { BarRow } from "@/components/ui/bars";
import { Button } from "@/components/ui/button";
import { PageTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Panel } from "@/features/insights/shared";
import { errorMessage } from "@/hooks/queries";
import { useSimulation } from "@/hooks/admin";
import { barWidths, mins, pct, signed } from "@/lib/insights";
import { BOUNDS, comparisonScenario, defaultScenario, MAX_SCENARIOS, validateScenarios } from "@/lib/simulation";
import type { Scenario } from "@/types/api";

type NumericKey = keyof typeof BOUNDS;
const KEYS = Object.keys(BOUNDS) as NumericKey[];

export default function SimulationPage() {
  const { clinicId, role } = useClinicCtx();
  const [scenarios, setScenarios] = useState<Scenario[]>([defaultScenario()]);
  const [problem, setProblem] = useState<string | null>(null);
  const sim = useSimulation(clinicId);

  if (role !== "CLINIC_ADMIN") return <p className="text-sm text-slate-600">Only clinic administrators can use the simulation lab.</p>;

  const update = (i: number, patch: Partial<Scenario>) => setScenarios((list) => list.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const run = () => {
    const err = validateScenarios(scenarios);
    setProblem(err);
    if (!err) sim.mutate(scenarios);
  };
  const results = sim.data?.results ?? [];
  const waitWidths = barWidths(results.map((r) => r.outcome.mean_wait_minutes));

  return (
    <div className="space-y-6">
      <PageTitle title="Simulation lab" subtitle="Try a what-if on a made-up clinic. Nothing here uses or changes your real data." />
      <Alert tone="info">
        These results come from a <strong>synthetic simulator</strong>. They show how waits respond when you change something, not what will happen in your clinic.
      </Alert>

      <div className="grid gap-4 lg:grid-cols-3">
        {scenarios.map((s, i) => (
          <section key={i} aria-label={`Scenario ${i + 1}`} className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200/80">
            <div className="flex items-center justify-between gap-2">
              <label className="sr-only" htmlFor={`name-${i}`}>Scenario {i + 1} name</label>
              <input
                id={`name-${i}`} value={s.name} maxLength={60} onChange={(e) => update(i, { name: e.target.value })}
                className="w-full rounded-lg border border-transparent px-2 py-1 font-display text-lg font-semibold text-ink hover:border-slate-200 focus:border-teal-600"
              />
              {scenarios.length > 1 && (
                <button type="button" onClick={() => setScenarios((l) => l.filter((_, j) => j !== i))} className="shrink-0 text-xs font-medium text-red-800 underline">Remove</button>
              )}
            </div>
            <div className="mt-4 space-y-3">
              {KEYS.map((k) => (
                <div key={k} className="grid grid-cols-[1fr_5.5rem] items-center gap-3 text-sm">
                  <label htmlFor={`${k}-${i}`} className="text-slate-700">{BOUNDS[k].label}</label>
                  <input
                    id={`${k}-${i}`} type="number" inputMode="decimal" min={BOUNDS[k].min} max={BOUNDS[k].max} step={BOUNDS[k].step}
                    value={Number.isNaN(s[k]) ? "" : s[k]}
                    onChange={(e) => update(i, { [k]: e.target.value === "" ? Number.NaN : Number(e.target.value) } as Partial<Scenario>)}
                    className="tnum w-full rounded-lg border border-slate-300 px-2 py-1.5 text-right"
                  />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={run} loading={sim.isPending}>Run simulation</Button>
        {scenarios.length < MAX_SCENARIOS && (
          <Button variant="secondary" onClick={() => setScenarios((l) => [...l, comparisonScenario(l[l.length - 1] ?? defaultScenario())])}>
            Add a comparison
          </Button>
        )}
        <span className="text-xs text-slate-500">Same seed gives the same result, so differences come from what you changed.</span>
      </div>
      {problem && <Alert tone="error">{problem}</Alert>}
      {sim.isError && <Alert tone="error">{errorMessage(sim.error)}</Alert>}

      {results.length > 0 && sim.data && (
        <Panel title="Results" subtitle="Changes are compared with the first scenario.">
          <div className="space-y-3">
            {results.map((r, i) => <BarRow key={r.scenario.name} label={r.scenario.name} width={waitWidths[i] ?? 0} value={`${mins(r.outcome.mean_wait_minutes, 1)}`} tone={i === 0 ? "teal" : "amber"} />)}
          </div>
          <p className="mt-1 text-xs text-slate-500">Bars show the average wait.</p>
          <div className="mt-6 overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">Scenario</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Visits</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Average wait</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">90th percentile</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Waiting over 30 min</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Doctor busy</th>
                  <th scope="col" className="py-2 pl-3 text-right font-medium">Days running late</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {results.map((r) => (
                  <tr key={r.scenario.name}>
                    <th scope="row" className="py-3 pr-4 font-medium">{r.scenario.name}</th>
                    <td className="tnum px-3 py-3 text-right">{r.outcome.visits}</td>
                    <td className="tnum px-3 py-3 text-right">{mins(r.outcome.mean_wait_minutes, 1)} <Delta v={r.mean_wait_change_minutes} unit=" min" /></td>
                    <td className="tnum px-3 py-3 text-right">{mins(r.outcome.p90_wait_minutes, 1)} <Delta v={r.p90_wait_change_minutes} unit=" min" /></td>
                    <td className="tnum px-3 py-3 text-right">{pct(r.outcome.share_waiting_over_30_min)}</td>
                    <td className="tnum px-3 py-3 text-right">{pct(r.outcome.utilisation)}</td>
                    <td className="tnum py-3 pl-3 text-right">{pct(r.outcome.overtime_day_share)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-xs leading-relaxed text-slate-500">{sim.data.note}</p>
        </Panel>
      )}
    </div>
  );
}

/** Change against the first scenario. For waits, lower is better, so a rise is shown in amber and a drop in green. */
function Delta({ v, unit }: { v: number | null; unit: string }) {
  if (v === null || Math.abs(v) < 0.05) return null;
  return <span className={v > 0 ? "text-xs text-amber-800" : "text-xs text-emerald-800"}>({signed(v, unit)})</span>;
}
