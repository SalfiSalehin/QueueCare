"use client";

import { useState } from "react";
import { PageTitle } from "@/components/ui/card";
import { ActivitySection } from "@/features/platform/activity";
import { ClinicsSection } from "@/features/platform/clinics";
import { useMe } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { isPlatformAdmin } from "@/lib/platform";

const TABS = [
  { id: "clinics", label: "Clinics" },
  { id: "activity", label: "Activity" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function PlatformPage() {
  const me = useMe();
  const [tab, setTab] = useState<TabId>("clinics");

  // The API refuses every platform call unless the user is a platform administrator; this also covers a typed URL.
  if (!isPlatformAdmin(me.data?.user)) {
    return <p className="text-sm text-slate-600">Only platform administrators can open this page.</p>;
  }

  return (
    <div className="space-y-6">
      <PageTitle title="Platform" subtitle="Approve new clinics, suspend or reopen existing ones, and see what changed. Changes apply straight away." />
      <div role="tablist" aria-label="Platform sections" className="inline-flex flex-wrap gap-1 rounded-2xl bg-white p-1 shadow-xs ring-1 ring-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={cn("rounded-xl px-4 py-2 text-sm font-medium transition-colors", tab === t.id ? "bg-ink text-white" : "text-slate-600 hover:bg-slate-100")}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "clinics" && <ClinicsSection />}
      {tab === "activity" && <ActivitySection />}
    </div>
  );
}
