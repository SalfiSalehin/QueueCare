"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { PageTitle } from "@/components/ui/card";
import { Avatar } from "@/components/ui/avatar";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { Field } from "@/components/ui/field";
import { useDebouncedValue } from "@/hooks/debounce";
import { errorMessage, useDirectory, useJoinClinic, useMe } from "@/hooks/queries";
import { cleanQuery, DEBOUNCE_MS, hasMore, MAX_QUERY_LENGTH, nextLimit, PAGE_SIZE, resultSummary } from "@/lib/directory";

export default function ClinicDirectory() {
  const router = useRouter();
  const me = useMe();
  const [text, setText] = useState("");
  const query = useDebouncedValue(cleanQuery(text), DEBOUNCE_MS);
  // "Show more" raises the limit for the current search only; a new search starts again from the first page.
  const [paged, setPaged] = useState({ query: "", limit: PAGE_SIZE });
  const limit = paged.query === query ? paged.limit : PAGE_SIZE;
  const directory = useDirectory(query, limit);
  const join = useJoinClinic();
  const memberOf = new Set((me.data?.memberships ?? []).map((m) => m.clinic_id));

  return (
    <>
      <PageTitle title="Find a clinic" subtitle="Joining a clinic lets you book appointments and see your place in its queue." />
      <form role="search" onSubmit={(e) => e.preventDefault()} className="mb-4 max-w-md">
        <Field
          label="Search clinics"
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={MAX_QUERY_LENGTH}
          autoComplete="off"
          placeholder="Clinic name or address"
          hint="Every word you type must appear in the clinic's name or address."
        />
      </form>
      {directory.isLoading && <Spinner />}
      {directory.isError && <Alert tone="error">{errorMessage(directory.error)}</Alert>}
      {join.isError && <Alert tone="error" className="mb-4">{errorMessage(join.error)}</Alert>}
      {directory.data && (
        <p role="status" className="mb-3 text-sm text-slate-700">
          {directory.isPlaceholderData || cleanQuery(text) !== query ? "Searching…" : resultSummary(directory.data.items.length, directory.data.total, query)}
        </p>
      )}
      {directory.data && directory.data.items.length === 0 && !directory.isPlaceholderData && (
        query ? (
          <EmptyState title="No clinic matches that search.">
            Try fewer words or a different spelling.{" "}
            <button type="button" onClick={() => setText("")} className="font-medium text-teal-800 underline">Clear search</button>
          </EmptyState>
        ) : (
          <EmptyState title="No clinics are open yet.">A platform administrator must approve a clinic before it appears here.</EmptyState>
        )
      )}
      <ul className="grid gap-4 sm:grid-cols-2">
        {directory.data?.items.map((c) => (
          <li key={c.id}>
            <div className="flex h-full flex-col rounded-3xl bg-white p-5 shadow-xs ring-1 ring-slate-200/80">
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
      {directory.data && hasMore(directory.data.items.length, directory.data.total) && (
        <div className="mt-6 text-center">
          <Button variant="secondary" loading={directory.isFetching} onClick={() => setPaged({ query, limit: nextLimit(limit) })}>
            Show more clinics
          </Button>
        </div>
      )}
    </>
  );
}
