"use client";

import { useMemo, useState } from "react";
import { useClinicCtx } from "@/components/clinic-context";
import { PageTitle } from "@/components/ui/card";
import { DoctorsTab } from "@/features/insights/doctors";
import { ModelHealthTab } from "@/features/insights/model-health";
import { BusyTab, OverviewTab } from "@/features/insights/overview";
import { SlotAdviceTab } from "@/features/insights/slot-advice";
import { cn } from "@/lib/cn";
import { localDay } from "@/lib/format";
import { daysBack } from "@/lib/insights";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "doctors", label: "Doctors" },
  { id: "busy", label: "Busy times" },
  { id: "model", label: "Estimate quality" },
  { id: "slots", label: "Slot advice" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const RANGES = [{ days: 7, label: "7 days" }, { days: 30, label: "30 days" }, { days: 90, label: "90 days" }] as const;

export default function InsightsPage() {
  const { clinicId, clinic, role } = useClinicCtx();
  const [tab, setTab] = useState<TabId>("overview");
  const [days, setDays] = useState<number>(30);
  const today = localDay(new Date().toISOString(), clinic.timezone);
  const range = useMemo(() => daysBack(today, days), [today, days]);

  // The API refuses everyone but clinic admins; the layout only links here for them, and this guards a typed URL.
  if (role !== "CLINIC_ADMIN") return <p className="text-sm text-slate-600">Only clinic administrators can see insights.</p>;

  const usesRange = tab !== "slots";
  return (
    <div className="space-y-6">
      <PageTitle title="Insights" subtitle="Counts and statistics only. No patient names appear on this page." />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Insight sections" className="inline-flex flex-wrap gap-1 rounded-2xl bg-white p-1 shadow-xs ring-1 ring-slate-200">
          {TABS.map((t) => (
            <button
              key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
              className={cn("rounded-xl px-4 py-2 text-sm font-medium transition-colors", tab === t.id ? "bg-ink text-white" : "text-slate-600 hover:bg-slate-100")}
            >
              {t.label}
            </button>
          ))}
        </div>
        {usesRange && (
          <div role="group" aria-label="Date range" className="inline-flex gap-1 rounded-xl bg-slate-100 p-1 text-sm">
            {RANGES.map((r) => (
              <button
                key={r.days} type="button" aria-pressed={days === r.days} onClick={() => setDays(r.days)}
                className={cn("rounded-lg px-3 py-1.5 font-medium", days === r.days ? "bg-white text-ink shadow-xs" : "text-slate-600")}
              >
                Last {r.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div role="tabpanel">
        {tab === "overview" && <OverviewTab clinicId={clinicId} range={range} />}
        {tab === "doctors" && <DoctorsTab clinicId={clinicId} range={range} />}
        {tab === "busy" && <BusyTab clinicId={clinicId} range={range} />}
        {tab === "model" && <ModelHealthTab clinicId={clinicId} range={range} />}
        {tab === "slots" && <SlotAdviceTab clinicId={clinicId} />}
      </div>
    </div>
  );
}
