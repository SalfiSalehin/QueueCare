"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EstimatePanel } from "./estimate-panel";
import { Avatar } from "@/components/ui/avatar";
import { Alert, StatusBadge } from "@/components/ui/feedback";
import { errorMessage } from "@/hooks/queries";
import { useCallNext, useTokenAction } from "@/hooks/staff";
import { cn } from "@/lib/cn";
import { formatTime, plural } from "@/lib/format";
import { actionsFor } from "@/lib/queue-actions";
import type { ClinicRole, QueueAction, QueueBoard, QueueToken } from "@/types/api";

interface RowProps {
  clinicId: string; token: QueueToken; role: ClinicRole; timeZone: string; busy: boolean;
  onAct: (tokenId: string, action: QueueAction) => void;
}

function meta(token: QueueToken, timeZone: string): string {
  return `${token.source === "WALK_IN" ? "Walk-in" : "Booked"}, arrived ${formatTime(token.arrived_at, timeZone)}${token.position !== null ? `, position ${token.position}` : ""}`;
}

function Actions({ token, role, busy, onAct }: Omit<RowProps, "timeZone">) {
  return (
    <div className="flex flex-wrap gap-2">
      {actionsFor(token.status, role).map((a) => (
        <Button key={a.action} size="sm" variant={a.variant} disabled={busy} onClick={() => onAct(token.id, a.action)}>{a.label}</Button>
      ))}
    </div>
  );
}

/** The patient who is with the doctor (or has been called): the most prominent thing on the board. */
function ServingCard(props: RowProps) {
  const { token, timeZone } = props;
  return (
    <li className="rounded-2xl bg-ink p-5 text-white">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs text-teal-100">{token.status === "CALLED" ? "Called, on the way" : "With the doctor"}</p>
          <p className="tnum mt-1 font-display text-5xl font-semibold leading-none tracking-tight">{token.token_label}</p>
          <p className="mt-2 text-sm text-teal-50">{token.patient_name}</p>
          <p className="text-xs text-teal-100/70">{meta(token, timeZone)}</p>
        </div>
        <div className="flex flex-col items-end gap-3">
          {token.priority > 0 && <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-900">urgent</span>}
          <Actions {...props} />
        </div>
      </div>
    </li>
  );
}

function WaitingRow(props: RowProps) {
  const { token, timeZone, clinicId } = props;
  const [explain, setExplain] = useState(false);
  const next = token.position === 1;
  return (
    <li className={cn("rounded-2xl px-4 py-3", next ? "bg-mint/60 ring-1 ring-teal-700/20" : "bg-slate-50")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-4">
          <span className={cn("tnum grid h-12 min-w-[4.25rem] place-items-center rounded-xl px-3 font-display text-lg font-semibold", next ? "bg-ticket text-ink" : "bg-white text-ink ring-1 ring-slate-200")}>
            {token.token_label}
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium text-slate-900">{token.patient_name}
              {token.priority > 0 && <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-900">urgent</span>}
            </p>
            <p className="text-xs text-slate-500">{meta(token, timeZone)}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {token.status === "WAITING" && (
            <button type="button" aria-expanded={explain} onClick={() => setExplain((v) => !v)} className="text-xs font-medium text-teal-800 underline">
              {explain ? "Hide estimate" : "Wait estimate"}
            </button>
          )}
          <Actions {...props} />
        </div>
      </div>
      {explain && <EstimatePanel clinicId={clinicId} tokenId={token.id} />}
    </li>
  );
}

export function DoctorBoard({ clinicId, board, role, timeZone }: {
  clinicId: string; board: QueueBoard; role: ClinicRole; timeZone: string;
}) {
  const act = useTokenAction(clinicId);
  const callNext = useCallNext(clinicId);
  const busy = act.isPending || callNext.isPending;
  const error = act.error ?? callNext.error;
  const onAct = (tokenId: string, action: QueueAction) => act.mutate({ tokenId, action });

  return (
    <section aria-label={`Queue for ${board.doctor_name}`} className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200/80">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Avatar name={board.doctor_name} />
          <div>
            <h2 className="font-display text-xl font-semibold text-ink">{board.doctor_name}</h2>
            <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <StatusBadge status={board.doctor_status} />
              {plural(board.waiting.length, "person", "people")} waiting, {board.finished_today} seen today
            </p>
          </div>
        </div>
        <Button loading={callNext.isPending} disabled={busy || board.waiting.length === 0} onClick={() => callNext.mutate(board.doctor_id)}>
          Call next patient
        </Button>
      </div>

      {error && <Alert tone="error" className="mt-4">{errorMessage(error)}</Alert>}

      <ul className="mt-5 space-y-3">
        {board.serving.length === 0 && (
          <li className="rounded-2xl border border-dashed border-slate-300 px-5 py-6 text-center text-sm text-slate-500">
            Nobody is with the doctor. Call the next patient when ready.
          </li>
        )}
        {board.serving.map((t) => <ServingCard key={t.id} clinicId={clinicId} token={t} role={role} timeZone={timeZone} busy={busy} onAct={onAct} />)}
      </ul>

      <h3 className="mt-7 font-display text-sm font-semibold text-slate-700">Waiting ({board.waiting.length})</h3>
      {board.waiting.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">Nobody is waiting.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {board.waiting.map((t) => <WaitingRow key={t.id} clinicId={clinicId} token={t} role={role} timeZone={timeZone} busy={busy} onAct={onAct} />)}
        </ul>
      )}

      {board.skipped.length > 0 && (
        <>
          <h3 className="mt-7 font-display text-sm font-semibold text-slate-700">Skipped ({board.skipped.length})</h3>
          <ul className="mt-3 space-y-2 opacity-90">
            {board.skipped.map((t) => <WaitingRow key={t.id} clinicId={clinicId} token={t} role={role} timeZone={timeZone} busy={busy} onAct={onAct} />)}
          </ul>
        </>
      )}
    </section>
  );
}
