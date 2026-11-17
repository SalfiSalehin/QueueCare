"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { PageTitle } from "@/components/ui/card";
import { Avatar } from "@/components/ui/avatar";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { errorMessage, useDirectory, useJoinClinic, useMe } from "@/hooks/queries";

export default function ClinicDirectory() {
  const router = useRouter();
  const me = useMe();
  const directory = useDirectory();
  const join = useJoinClinic();
  const memberOf = new Set((me.data?.memberships ?? []).map((m) => m.clinic_id));

  return (
    <>
      <PageTitle title="Find a clinic" subtitle="Joining a clinic lets you book appointments and see your place in its queue." />
      {directory.isLoading && <Spinner />}
      {directory.isError && <Alert tone="error">{errorMessage(directory.error)}</Alert>}
      {join.isError && <Alert tone="error" className="mb-4">{errorMessage(join.error)}</Alert>}
      {directory.data && directory.data.items.length === 0 && (
        <EmptyState title="No clinics are open yet.">A platform administrator must approve a clinic before it appears here.</EmptyState>
      )}
      <ul className="grid gap-4 sm:grid-cols-2">
        {directory.data?.items.map((c) => (
          <li key={c.id}>
            <div className="flex h-full flex-col rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200/80">
              <div className="flex items-center gap-3">
                <Avatar name={c.name} />
                <div className="min-w-0">
                  <h2 className="truncate font-display text-lg font-semibold text-ink">{c.name}</h2>
                  <p className="text-xs text-slate-500">Time zone: {c.timezone}</p>
                </div>
              </div>
              <div className="mt-5">
                {memberOf.has(c.id) ? (
                  <Link href={`/app/c/${c.id}`} className="inline-block rounded-xl bg-mint px-4 py-2 text-sm font-semibold text-teal-900 hover:bg-teal-100">Open clinic</Link>
                ) : (
                  <Button
                    size="sm"
                    loading={join.isPending && join.variables === c.id}
                    onClick={() => join.mutate(c.id, { onSuccess: () => router.push(`/app/c/${c.id}`) })}
                  >
                    Join as a patient
                  </Button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
