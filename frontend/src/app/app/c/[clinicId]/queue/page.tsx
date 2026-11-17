"use client";

import { useClinicCtx } from "@/components/clinic-context";
import { Alert, EmptyState, Spinner, StatusBadge } from "@/components/ui/feedback";
import { errorMessage, useEstimate, useMyQueue } from "@/hooks/queries";
import { plural } from "@/lib/format";
import type { MyToken } from "@/types/api";

function TokenCard({ clinicId, token }: { clinicId: string; token: MyToken }) {
  const waiting = token.status === "WAITING";
  const estimate = useEstimate(clinicId, token.id, waiting);
  const e = estimate.data;

  return (
    <article className="overflow-hidden rounded-3xl bg-white shadow-sm ring-1 ring-slate-200/80">
      <div className="flex items-start justify-between gap-3 bg-ink px-6 py-6 text-white">
        <div>
          <p className="text-xs text-teal-100">Your token</p>
          <p className="tnum font-display text-6xl font-semibold leading-none tracking-tight">{token.token_label}</p>
          <p className="mt-2 text-sm text-teal-50/85">{token.doctor_name}</p>
        </div>
        <StatusBadge status={token.status} />
      </div>
      <div className="px-6 py-5">
        {token.status === "CALLED" && <Alert tone="success">It is your turn. Please go to the consultation room.</Alert>}
        {waiting && (
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div className="rounded-2xl bg-mint/60 px-4 py-3">
              <dt className="text-slate-600">Ahead of you</dt>
              <dd className="font-display text-2xl font-semibold text-ink">{token.people_ahead === null ? "–" : plural(token.people_ahead, "person", "people")}</dd>
            </div>
            <div className="rounded-2xl bg-slate-100 px-4 py-3">
              <dt className="text-slate-600">Estimated wait</dt>
              <dd className="font-display text-2xl font-semibold text-ink">
                {estimate.isLoading ? "…" : e?.median_minutes == null ? "not available" : e.median_minutes < 1 ? "you are next" : `about ${Math.round(e.median_minutes)} min`}
              </dd>
            </div>
          </dl>
        )}
        {waiting && e && (
          <p className="mt-4 text-xs leading-relaxed text-slate-500">
            {e.source === "model" ? "Estimate from a statistical model trained on simulated data. " : "Estimate from a simple rule, not a model. "}
            {e.note} Waits can change; this is not a promise.
          </p>
        )}
        {!waiting && token.status !== "CALLED" && <p className="text-sm text-slate-600">Nothing more to do for this token.</p>}
      </div>
    </article>
  );
}

export default function QueuePage() {
  const { clinicId } = useClinicCtx();
  const queue = useMyQueue(clinicId);
  return (
    <div className="space-y-4">
      {queue.isLoading && <Spinner />}
      {queue.isError && <Alert tone="error">{errorMessage(queue.error)}</Alert>}
      {queue.data && queue.data.length === 0 && (
        <EmptyState title="You are not in today's queue.">
          When you arrive, the front desk checks you in and your token appears here.
        </EmptyState>
      )}
      {queue.data?.map((t) => <TokenCard key={t.id} clinicId={clinicId} token={t} />)}
      <p className="text-xs text-slate-500">This page refreshes every few seconds (it does not use live push yet).</p>
    </div>
  );
}
