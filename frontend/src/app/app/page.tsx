"use client";

import Link from "next/link";
import { Avatar } from "@/components/ui/avatar";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { errorMessage, useDirectory, useMe } from "@/hooks/queries";

export default function Dashboard() {
  const me = useMe();
  const directory = useDirectory();
  if (!me.data) return null;
  const memberships = me.data.memberships;
  const names = new Map((directory.data?.items ?? []).map((c) => [c.id, c.name]));
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

      <h2 className="mb-4 mt-9 font-display text-xl font-semibold text-ink">Your clinics</h2>
      {directory.isLoading && <Spinner />}
      {directory.isError && <Alert tone="error">{errorMessage(directory.error)}</Alert>}
      {memberships.length === 0 ? (
        <EmptyState title="You have not joined a clinic yet.">
          <Link href="/app/clinics" className="font-medium text-teal-800 underline">Find a clinic to join</Link>
        </EmptyState>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {memberships.map((m) => {
            const name = names.get(m.clinic_id) ?? "Clinic";
            return (
              <li key={m.clinic_id}>
                <Link
                  href={`/app/c/${m.clinic_id}`}
                  className="flex items-center gap-4 rounded-3xl bg-white p-5 shadow-xs ring-1 ring-slate-200/80 transition hover:-translate-y-0.5 hover:shadow-lift"
                >
                  <Avatar name={name} />
                  <span className="min-w-0">
                    <span className="block truncate font-display text-lg font-semibold text-ink">{name}</span>
                    <span className="text-sm text-slate-500">You are a {m.role.replace("_", " ").toLowerCase()}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
