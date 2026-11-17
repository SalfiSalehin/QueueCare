"use client";

import Link from "next/link";
import { useClinicCtx } from "@/components/clinic-context";
import { CalendarDays, Ticket } from "lucide-react";
import { Spinner, StatusBadge } from "@/components/ui/feedback";
import { useAppointments, useMyQueue } from "@/hooks/queries";
import { formatDateTime } from "@/lib/format";

export default function ClinicHome() {
  const { clinicId, clinic } = useClinicCtx();
  const appts = useAppointments(clinicId);
  const queue = useMyQueue(clinicId);
  const now = Date.now();
  const upcoming = (appts.data?.items ?? [])
    .filter((a) => ["PENDING", "CONFIRMED"].includes(a.status) && new Date(a.starts_at).getTime() > now)
    .sort((a, b) => (a.starts_at < b.starts_at ? -1 : 1));
  const next = upcoming[0];
  const active = (queue.data ?? []).filter((t) => ["WAITING", "CALLED", "IN_CONSULTATION"].includes(t.status));

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <section className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200/80">
        <CalendarDays aria-hidden className="h-6 w-6 text-teal-700" />
        <h2 className="mt-3 font-display text-xl font-semibold text-ink">Next appointment</h2>
        {appts.isLoading ? <Spinner /> : next ? (
          <>
            <p className="mt-3 font-display text-2xl font-semibold text-ink">{formatDateTime(next.starts_at, clinic.timezone)}</p>
            <p className="text-sm text-slate-600">with {next.doctor_name} <StatusBadge status={next.status} /></p>
            <Link href={`/app/c/${clinicId}/appointments`} className="mt-4 inline-block rounded-xl bg-mint px-4 py-2 text-sm font-semibold text-teal-900 hover:bg-teal-100">Manage appointments</Link>
          </>
        ) : (
          <>
            <p className="mt-2 text-sm text-slate-600">You have nothing booked.</p>
            <Link href={`/app/c/${clinicId}/book`} className="mt-4 inline-block rounded-xl bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800">Book an appointment</Link>
          </>
        )}
      </section>
      <section className="rounded-3xl bg-ink p-6 text-white shadow-sm">
        <Ticket aria-hidden className="h-6 w-6 text-ticket" />
        <h2 className="mt-3 font-display text-xl font-semibold">Today&apos;s queue</h2>
        {queue.isLoading ? <Spinner /> : active.length > 0 ? (
          <>
            <p className="tnum mt-3 font-display text-4xl font-semibold">{active[0]?.token_label}</p>
            <p className="text-sm text-teal-50/85">{active[0]?.status === "WAITING" ? "You are in the queue." : "It is your turn."}</p>
            <Link href={`/app/c/${clinicId}/queue`} className="mt-4 inline-block rounded-xl bg-ticket px-4 py-2 text-sm font-semibold text-ink hover:brightness-95">See live position</Link>
          </>
        ) : (
          <p className="mt-3 text-sm text-teal-50/85">You are not in a queue right now. The front desk adds you when you arrive.</p>
        )}
      </section>
    </div>
  );
}
