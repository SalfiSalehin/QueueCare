"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useClinicCtx } from "@/components/clinic-context";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { Card } from "@/components/ui/card";
import { Alert, EmptyState, Spinner, StatusBadge } from "@/components/ui/feedback";
import { errorMessage, useAlternatives, useBook, useDoctors, useSlots } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDayHeading, formatTime, groupByDay, plural } from "@/lib/format";
import type { Slot } from "@/types/api";

function Step({ n }: { n: number }) {
  return <span aria-hidden className="tnum grid h-8 w-8 place-items-center rounded-full bg-ink font-display text-sm font-semibold text-ticket">{n}</span>;
}

export default function BookPage() {
  const router = useRouter();
  const { clinicId, clinic } = useClinicCtx();
  const tz = clinic.timezone;
  const doctors = useDoctors(clinicId);
  const [doctorId, setDoctorId] = useState<string | null>(null);
  const [picked, setPicked] = useState<Slot | null>(null);
  const slots = useSlots(clinicId, doctorId);
  const book = useBook(clinicId);
  const taken = book.error instanceof ApiError && book.error.status === 409;
  const noSlots = slots.data?.length === 0;
  const alternatives = useAlternatives(clinicId, doctorId, taken || noSlots);
  const doctor = doctors.data?.items.find((d) => d.id === doctorId);

  const choose = (id: string) => { setDoctorId(id); setPicked(null); book.reset(); };
  const confirm = () => {
    if (!doctorId || !picked) return;
    book.mutate({ doctorId, startsAt: picked.starts_at }, {
      onSuccess: () => router.push(`/app/c/${clinicId}/appointments`),
      onError: () => setPicked(null),
    });
  };

  return (
    <div className="space-y-6">
      <section aria-labelledby="doc-h">
        <h2 id="doc-h" className="mb-4 flex items-center gap-3 font-display text-xl font-semibold text-ink"><Step n={1} />Choose a doctor</h2>
        {doctors.isLoading && <Spinner />}
        {doctors.isError && <Alert tone="error">{errorMessage(doctors.error)}</Alert>}
        {doctors.data && doctors.data.items.length === 0 && <EmptyState title="This clinic has no doctors yet." />}
        <ul className="grid gap-3 sm:grid-cols-2">
          {doctors.data?.items.filter((d) => d.is_active).map((d) => (
            <li key={d.id}>
              <button
                type="button" onClick={() => choose(d.id)} aria-pressed={doctorId === d.id}
                className={cn("flex w-full items-center gap-4 rounded-3xl bg-white p-4 text-left shadow-xs transition hover:shadow-lift", doctorId === d.id ? "ring-2 ring-teal-700" : "ring-1 ring-slate-200/80")}
              >
                <Avatar name={d.display_name} />
                <span className="min-w-0">
                  <span className="block truncate font-display text-lg font-semibold text-ink">{d.display_name}</span>
                  <span className="mt-1 flex items-center gap-2 text-xs text-slate-600">
                    {d.default_slot_minutes}-minute visits <StatusBadge status={d.status} />
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {doctorId && (
        <section aria-labelledby="slot-h">
          <h2 id="slot-h" className="mb-4 flex flex-wrap items-center gap-x-3 font-display text-xl font-semibold text-ink"><Step n={2} />Pick a time <span className="font-sans text-sm font-normal text-slate-500">(clinic time, {tz})</span></h2>
          {slots.isLoading && <Spinner label="Loading times" />}
          {slots.isError && <Alert tone="error">{errorMessage(slots.error)}</Alert>}
          {taken && <Alert tone="warning" className="mb-3">{errorMessage(book.error)}</Alert>}
          {book.isError && !taken && <Alert tone="error" className="mb-3">{errorMessage(book.error)}</Alert>}
          {noSlots && <EmptyState title={`${doctor?.display_name ?? "This doctor"} has no free times in the coming days.`} />}
          <div className="space-y-4">
            {groupByDay(slots.data ?? [], (s) => s.starts_at, tz).map(([day, list]) => (
              <Card key={day} className="rounded-3xl p-5">
                <h3 className="font-display text-base font-semibold text-ink">{formatDayHeading(day)} <span className="font-sans text-sm font-normal text-slate-500">({plural(list.length, "time")})</span></h3>
                <ul className="mt-3 flex flex-wrap gap-2">
                  {list.map((s) => (
                    <li key={s.starts_at}>
                      <button
                        type="button" onClick={() => setPicked(s)} aria-pressed={picked?.starts_at === s.starts_at}
                        className={cn("tnum rounded-xl border px-4 py-2 text-sm font-medium transition-colors", picked?.starts_at === s.starts_at ? "border-ink bg-ink text-white" : "border-slate-200 bg-mint/50 text-teal-950 hover:border-teal-600")}
                      >
                        {formatTime(s.starts_at, tz)}
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </div>

          {(taken || noSlots) && alternatives.data && alternatives.data.alternatives.length > 0 && (
            <Card className="mt-4">
              <h3 className="font-medium">Other doctors with the earliest openings</h3>
              <ul className="mt-2 space-y-2 text-sm">
                {alternatives.data.alternatives.map((a) => (
                  <li key={a.doctor_id} className="flex items-center justify-between gap-3">
                    <span>{a.display_name}{a.earliest && <span className="text-slate-600"> · from {formatDateTime(a.earliest.starts_at, tz)}</span>}</span>
                    <Button size="sm" variant="secondary" onClick={() => choose(a.doctor_id)}>See times</Button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </section>
      )}

      {picked && doctor && (
        <section aria-labelledby="confirm-h" className="sticky bottom-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl bg-ink p-5 text-white shadow-lift">
            <div>
              <h2 id="confirm-h" className="font-display text-lg font-semibold">Confirm booking</h2>
              <p className="text-sm text-teal-50/85">{doctor.display_name}, {formatDateTime(picked.starts_at, tz)}</p>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setPicked(null)}>Change</Button>
              <Button loading={book.isPending} onClick={confirm} className="!bg-ticket !text-ink hover:brightness-95">Book this time</Button>
            </div>
          </div>
        </section>
      )}
      <p className="text-xs text-slate-500">
        Need to see appointments you already have? <Link href={`/app/c/${clinicId}/appointments`} className="underline">Open appointments</Link>.
      </p>
    </div>
  );
}
