"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { Avatar } from "@/components/ui/avatar";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { errorMessage, keys, useDirectory, useMe } from "@/hooks/queries";
import { clinicStatusNote } from "@/lib/register-clinic";
import { clinicService } from "@/services/clinics";

const REGISTER_LINK = "rounded-xl bg-mint px-4 py-2 text-sm font-semibold text-teal-900 hover:bg-teal-100";

export default function Dashboard() {
  const me = useMe();
  const directory = useDirectory();
  const memberships = me.data?.memberships ?? [];
  const names = new Map((directory.data?.items ?? []).map((c) => [c.id, c.name]));
  // The open-clinic list holds only clinics that are open. A clinic still waiting for approval (or closed) is read directly, so
  // its owner sees its name and state instead of a nameless card. Same query key as the clinic page, so the answer is shared.
  const unlisted = directory.data ? memberships.filter((m) => !names.has(m.clinic_id)) : [];
  const details = useQueries({
    queries: unlisted.map((m) => ({ queryKey: keys.clinic(m.clinic_id), queryFn: () => clinicService.get(m.clinic_id) })),
  });
  const detail = new Map(unlisted.map((m, i) => [m.clinic_id, details[i]?.data]));

  if (!me.data) return null;
  const first = me.data.user.full_name.split(/\s+/)[0] ?? me.data.user.full_name;

  return (
    <>
      <section className="relative overflow-hidden rounded-3xl bg-ink px-7 py-8 text-white">
        <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-teal-600/30 blur-3xl" />
        <h1 className="relative font-display text-3xl font-semibold tracking-tight">Welcome, {first}</h1>
        <p className="relative mt-2 max-w-md text-sm text-teal-50/85">
          {memberships.length === 0 ? "Find a clinic to join, then book a time or follow your place in the queue." : "Open a clinic to book, check your appointments or follow the queue."}
        </p>
      </section>

      <div className="mb-4 mt-9 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-xl font-semibold text-ink">Your clinics</h2>
        <Link href="/app/register-clinic" className={REGISTER_LINK}>Register a clinic</Link>
      </div>
      {directory.isLoading && <Spinner />}
      {directory.isError && <Alert tone="error">{errorMessage(directory.error)}</Alert>}
      {memberships.length === 0 ? (
        <EmptyState title="You have not joined a clinic yet.">
          <Link href="/app/clinics" className="font-medium text-teal-800 underline">Find a clinic to join</Link>
          {" "}or{" "}
          <Link href="/app/register-clinic" className="font-medium text-teal-800 underline">register your own</Link>
        </EmptyState>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {memberships.map((m) => {
            const info = detail.get(m.clinic_id);
            const name = names.get(m.clinic_id) ?? info?.name ?? "Clinic";
            const note = clinicStatusNote(info?.status);
            const card = "flex items-center gap-4 rounded-3xl bg-white p-5 shadow-xs ring-1 ring-slate-200/80";
            const body = (
              <>
                <Avatar name={name} />
                <span className="min-w-0">
                  <span className="block truncate font-display text-lg font-semibold text-ink">{name}</span>
                  <span className="text-sm text-slate-500">You are a {m.role.replace("_", " ").toLowerCase()}</span>
                  {note && <span className="mt-1 block text-sm font-medium text-amber-800">{note}</span>}
                </span>
              </>
            );
            return (
              <li key={m.clinic_id}>
                {/* A clinic that is not open has no pages to show yet, so its card is not a link. */}
                {note ? (
                  <div className={card}>{body}</div>
                ) : (
                  <Link href={`/app/c/${m.clinic_id}`} className={`${card} transition hover:-translate-y-0.5 hover:shadow-lift`}>{body}</Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
