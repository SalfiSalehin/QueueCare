"use client";

import { useState } from "react";
import { useClinicCtx } from "@/components/clinic-context";
import { PageTitle } from "@/components/ui/card";
import { DepartmentsSection } from "@/features/setup/departments";
import { DoctorsSection } from "@/features/setup/doctors";
import { TeamSection } from "@/features/setup/team";
import { cn } from "@/lib/cn";

const TABS = [
  { id: "doctors", label: "Doctors" },
  { id: "departments", label: "Departments" },
  { id: "team", label: "Team" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function SetupPage() {
  const { clinicId, clinic, role } = useClinicCtx();
  const [tab, setTab] = useState<TabId>("doctors");

  // The API refuses every change unless the user is a clinic administrator; this also covers a typed URL.
  if (role !== "CLINIC_ADMIN") return <p className="text-sm text-slate-600">Only clinic administrators can set up the clinic.</p>;

  return (
    <div className="space-y-6">
      <PageTitle title="Clinic setup" subtitle="Departments, doctors and their hours, and your team. Changes apply to booking and the queue straight away." />
      <div role="tablist" aria-label="Setup sections" className="inline-flex flex-wrap gap-1 rounded-2xl bg-white p-1 shadow-sm ring-1 ring-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={cn("rounded-xl px-4 py-2 text-sm font-medium transition-colors", tab === t.id ? "bg-ink text-white" : "text-slate-600 hover:bg-slate-100")}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "doctors" && <DoctorsSection clinicId={clinicId} timeZone={clinic.timezone} />}
      {tab === "departments" && <DepartmentsSection clinicId={clinicId} />}
      {tab === "team" && <TeamSection clinicId={clinicId} />}
    </div>
  );
}
