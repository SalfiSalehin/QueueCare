"use client";

import { StatTile } from "@/components/ui/card";
import { BarRow } from "@/components/ui/bars";
import { useLoad, useOverview } from "@/hooks/admin";
import { barWidths, hourLabel, mins, pct, WEEKDAYS } from "@/lib/insights";
import { Panel, QueryBoundary, words } from "./shared";

interface Props { clinicId: string; range: { start: string; end: string } }

export function OverviewTab({ clinicId, range }: Props) {
  const q = useOverview(clinicId, range);
  const d = q.data;
  const daily = d?.daily ?? [];
  const heights = barWidths(daily.map((p) => p.consultations));

  return (
    <div className="space-y-6">
      <QueryBoundary isLoading={q.isLoading} error={q.error}>
        {d && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <StatTile tone="dark" label="Appointments" value={d.appointments_total} />
              <StatTile label="No-show rate" value={pct(d.no_show_rate, 1)} />
              <StatTile label="Cancellation rate" value={pct(d.cancellation_rate, 1)} />
              <StatTile label="Walk-in share of queue" value={pct(d.walk_in_share, 0)} />
              <StatTile label="Typical wait (median)" value={mins(d.wait_minutes.p50)} />
              <StatTile label="Long waits (90th percentile)" value={mins(d.wait_minutes.p90)} />
            </div>
            <p className="text-xs text-slate-500">
              Wait is the time from arriving to starting the consultation, based on {d.wait_minutes.n} visits. A dash means there is no data yet, not zero.
              Dates are clinic time ({d.range.timezone}).
            </p>

            <Panel title="Visits per day" subtitle="Completed consultations on each day in the range.">
              {daily.length === 0 || daily.every((p) => p.consultations === 0) ? (
                <p className="text-sm text-slate-500">No completed consultations in this range.</p>
              ) : (
                <>
                  <div className="flex h-40 items-end gap-1" role="img" aria-label="Bar chart of completed consultations per day">
                    {daily.map((p, i) => (
                      <div key={p.date} className="group relative flex h-full flex-1 items-end" title={`${p.date}: ${p.consultations}`}>
                        <span className="block w-full rounded-t bg-teal-600/90" style={{ height: `${heights[i] ?? 0}%` }} />
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-slate-500"><span>{daily[0]?.date}</span><span>{daily[daily.length - 1]?.date}</span></div>
                </>
              )}
            </Panel>

            <div className="grid gap-6 md:grid-cols-2">
              <Panel title="Appointments by status">
                <StatusList counts={d.appointments_by_status} empty="No appointments in this range." />
              </Panel>
              <Panel title="Queue tokens by status">
                <StatusList counts={d.tokens_by_status} empty="Nobody has joined the queue in this range." />
              </Panel>
            </div>
          </>
        )}
      </QueryBoundary>
    </div>
  );
}

function StatusList({ counts, empty }: { counts: Record<string, number>; empty: string }) {
  const rows = Object.entries(counts).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return <p className="text-sm text-slate-500">{empty}</p>;
  const widths = barWidths(rows.map(([, n]) => n));
  return (
    <div className="space-y-3">
      {rows.map(([status, n], i) => <BarRow key={status} label={words(status)} value={String(n)} width={widths[i] ?? 0} />)}
    </div>
  );
}

export function BusyTab({ clinicId, range }: Props) {
  const q = useLoad(clinicId, range);
  const d = q.data;
  const hours = (d?.by_hour ?? []).filter((h) => h.arrivals > 0);
  const hw = barWidths(hours.map((h) => h.arrivals));
  const days = d?.by_weekday ?? [];
  const dw = barWidths(days.map((w) => w.arrivals));

  return (
    <QueryBoundary isLoading={q.isLoading} error={q.error}>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Arrivals by hour" subtitle="When patients arrive, with the average wait of those who arrived in that hour.">
          {hours.length === 0 ? <p className="text-sm text-slate-500">No arrivals in this range.</p> : (
            <div className="space-y-3">
              {hours.map((h, i) => (
                <BarRow key={h.hour} label={hourLabel(h.hour)} width={hw[i] ?? 0} value={`${h.arrivals} · ${mins(h.avg_wait_minutes)}`} />
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Arrivals by weekday">
          {days.every((w) => w.arrivals === 0) ? <p className="text-sm text-slate-500">No arrivals in this range.</p> : (
            <div className="space-y-3">
              {days.map((w, i) => <BarRow key={w.weekday} label={WEEKDAYS[w.weekday] ?? String(w.weekday)} width={dw[i] ?? 0} value={String(w.arrivals)} tone="amber" />)}
            </div>
          )}
        </Panel>
      </div>
    </QueryBoundary>
  );
}
