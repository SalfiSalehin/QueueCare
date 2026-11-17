"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ClinicContext } from "@/components/clinic-context";
import { Alert, Spinner } from "@/components/ui/feedback";
import { errorMessage, useClinic, useMe } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { isStaff } from "@/lib/queue-actions";

function RedirectTo({ href }: { href: string }) {
  const router = useRouter();
  useEffect(() => { router.replace(href); }, [router, href]);
  return <Spinner />;
}

export default function ClinicLayout({ children }: { children: ReactNode }) {
  const { clinicId } = useParams<{ clinicId: string }>();
  const pathname = usePathname();
  const me = useMe();
  const clinic = useClinic(clinicId);
  const membership = me.data?.memberships.find((m) => m.clinic_id === clinicId);

  if (me.isLoading || clinic.isLoading) return <Spinner />;
  // The API answers 404 for clinics you do not belong to, so a missing clinic and a forbidden one look the same.
  if (!membership || clinic.isError || !clinic.data) {
    return (
      <Alert tone="warning">
        {clinic.isError ? errorMessage(clinic.error) : "You are not a member of this clinic."}{" "}
        <Link href="/app/clinics" className="font-medium underline">Find a clinic</Link>
      </Alert>
    );
  }
  const base = `/app/c/${clinicId}`;
  const staff = isStaff(membership.role);
  const isAdmin = membership.role === "CLINIC_ADMIN";
  const tabs = staff
    ? [
        { href: `${base}/board`, label: "Queue board" },
        ...(isAdmin ? [{ href: `${base}/insights`, label: "Insights" }, { href: `${base}/simulation`, label: "Simulation lab" }, { href: `${base}/setup`, label: "Setup" }] : []),
      ]
    : [
        { href: base, label: "Overview" },
        { href: `${base}/book`, label: "Book" },
        { href: `${base}/appointments`, label: "Appointments" },
        { href: `${base}/queue`, label: "My queue" },
      ];
  // Staff have no patient pages: send them to the board. (Patients are not sent to the board; the API refuses them anyway.)
  const staffPaths = tabs.map((t) => t.href);
  const wrongArea = staff ? !staffPaths.includes(pathname) : [`${base}/board`, `${base}/insights`, `${base}/simulation`, `${base}/setup`].includes(pathname);
  if (wrongArea) return <RedirectTo href={staff ? `${base}/board` : base} />;
  return (
    <ClinicContext.Provider value={{ clinicId, clinic: clinic.data, role: membership.role }}>
      <div className="mb-6">
        <h1 className="font-display text-3xl font-semibold tracking-tight text-ink">{clinic.data.name}</h1>
        {staff && <p className="mt-1 text-sm text-slate-600">Signed in as {membership.role.replace("_", " ").toLowerCase()}</p>}
        <nav aria-label="Clinic" className="mt-5 inline-flex flex-wrap gap-1 rounded-2xl bg-white p-1 shadow-sm ring-1 ring-slate-200">
          {tabs.map((t) => {
            const active = pathname === t.href;
            return (
              <Link
                key={t.href} href={t.href} aria-current={active ? "page" : undefined}
                className={cn("rounded-xl px-4 py-2 text-sm font-medium transition-colors", active ? "bg-ink text-white" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900")}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </ClinicContext.Provider>
  );
}
