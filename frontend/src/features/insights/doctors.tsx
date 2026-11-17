"use client";

import { useDoctorStats } from "@/hooks/admin";
import { mins, pct } from "@/lib/insights";
import { Panel, QueryBoundary } from "./shared";

export function DoctorsTab({ clinicId, range }: { clinicId: string; range: { start: string; end: string } }) {
  const q = useDoctorStats(clinicId, range);
  const items = q.data?.items ?? [];
  return (
    <QueryBoundary isLoading={q.isLoading} error={q.error}>
      <Panel
        title="Doctors"
        subtitle="Booked use is how much of the scheduled time is booked. Busy use is time actually spent with patients."
      >
        {items.length === 0 ? (
          <p className="text-sm text-slate-500">No doctors with a schedule in this range.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">Doctor</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Patients seen</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Average wait</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Booked use</th>
                  <th scope="col" className="py-2 pl-4 text-right font-medium">Busy use</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((d) => (
                  <tr key={d.doctor_id}>
                    <th scope="row" className="py-3 pr-4 font-medium text-slate-900">{d.display_name}</th>
                    <td className="tnum px-4 py-3 text-right">{d.patients_seen}</td>
                    <td className="tnum px-4 py-3 text-right">{mins(d.avg_wait_minutes)}</td>
                    <td className="tnum px-4 py-3 text-right">{pct(d.booked_utilisation)}</td>
                    <td className="tnum py-3 pl-4 text-right">{pct(d.busy_utilisation)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </QueryBoundary>
  );
}
