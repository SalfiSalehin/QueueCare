"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Alert, Spinner } from "@/components/ui/feedback";
import { Field, SelectField } from "@/components/ui/field";
import { errorMessage } from "@/hooks/queries";
import { useAddSchedule, useAddTimeOff, useDeleteSchedule, useDeleteTimeOff, useSchedules, useTimeOff } from "@/hooks/setup";
import { formatDateTime } from "@/lib/format";
import { DAY_NAMES, localToUtcIso, validateTimeOff, validateWindow, windowLabel } from "@/lib/setup";

/** Weekly working hours, in the clinic's local time. Patients can only book inside these hours. */
export function ScheduleEditor({ clinicId, doctorId, timeZone }: { clinicId: string; doctorId: string; timeZone: string }) {
  const schedules = useSchedules(clinicId, doctorId);
  const add = useAddSchedule(clinicId, doctorId);
  const del = useDeleteSchedule(clinicId, doctorId);
  const [day, setDay] = useState(0);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");
  const [problem, setProblem] = useState<string | null>(null);
  const rows = schedules.data ?? [];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const bad = validateWindow(start, end, rows, day);
    setProblem(bad);
    if (!bad) add.mutate({ day, start, end });
  };

  return (
    <div>
      <h3 className="font-display text-lg font-semibold text-ink">Weekly hours</h3>
      <p className="text-sm text-slate-600">Times are in the clinic&apos;s time zone ({timeZone}).</p>
      {schedules.isLoading && <div className="mt-3"><Spinner /></div>}
      {schedules.isError && <Alert tone="error" className="mt-3">{errorMessage(schedules.error)}</Alert>}
      {schedules.data && rows.length === 0 && (
        <p className="mt-3 text-sm text-slate-600">No hours yet. Patients cannot book this doctor until you add some.</p>
      )}
      <ul className="mt-3 divide-y divide-slate-100">
        {DAY_NAMES.map((name, i) => {
          const mine = rows.filter((r) => r.day_of_week === i).sort((a, b) => (a.start_time < b.start_time ? -1 : 1));
          if (mine.length === 0) return null;
          return (
            <li key={name} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-2">
              <span className="w-28 text-sm font-medium text-slate-800">{name}</span>
              <span className="flex flex-wrap gap-2">
                {mine.map((w) => (
                  <span key={w.id} className="inline-flex items-center gap-1 rounded-full bg-mint px-3 py-1 text-sm text-teal-900">
                    {windowLabel(w.start_time, w.end_time)}
                    <button
                      type="button" aria-label={`Remove ${name} ${windowLabel(w.start_time, w.end_time)}`} disabled={del.isPending}
                      onClick={() => del.mutate(w.id)} className="ml-1 rounded-full px-1.5 text-teal-900 hover:bg-white/70"
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
      <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-3" noValidate>
        <SelectField label="Day" value={day} onChange={(e) => setDay(Number(e.target.value))}>
          {DAY_NAMES.map((n, i) => <option key={n} value={i}>{n}</option>)}
        </SelectField>
        <Field label="From" type="time" value={start} onChange={(e) => setStart(e.target.value)} />
        <Field label="To" type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
        <div className="sm:col-span-3"><Button type="submit" loading={add.isPending}>Add hours</Button></div>
      </form>
      <div className="mt-3 space-y-2">
        {problem && <Alert tone="error">{problem}</Alert>}
        {add.error && <Alert tone="error">{errorMessage(add.error)}</Alert>}
        {del.error && <Alert tone="error">{errorMessage(del.error)}</Alert>}
      </div>
    </div>
  );
}

/** Dates a doctor is away. Slots inside them disappear from booking. */
export function TimeOffEditor({ clinicId, doctorId, timeZone }: { clinicId: string; doctorId: string; timeZone: string }) {
  const list = useTimeOff(clinicId, doctorId);
  const add = useAddTimeOff(clinicId, doctorId);
  const del = useDeleteTimeOff(clinicId, doctorId);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const bad = validateTimeOff(from, to, timeZone);
    setProblem(bad);
    const s = localToUtcIso(from, timeZone);
    const en = localToUtcIso(to, timeZone);
    if (bad || !s || !en) return;
    add.mutate({ startsAtUtc: s, endsAtUtc: en, reason: reason.trim() || null }, { onSuccess: () => { setFrom(""); setTo(""); setReason(""); } });
  };

  return (
    <div>
      <h3 className="font-display text-lg font-semibold text-ink">Time off</h3>
      <p className="text-sm text-slate-600">Upcoming days away. Times are in the clinic&apos;s time zone ({timeZone}).</p>
      {list.isLoading && <div className="mt-3"><Spinner /></div>}
      {list.isError && <Alert tone="error" className="mt-3">{errorMessage(list.error)}</Alert>}
      {list.data && list.data.length === 0 && <p className="mt-3 text-sm text-slate-600">No upcoming time off.</p>}
      <ul className="mt-3 divide-y divide-slate-100">
        {list.data?.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <span>
              {formatDateTime(t.starts_at, timeZone)} to {formatDateTime(t.ends_at, timeZone)}
              {t.reason && <span className="text-slate-600"> &middot; {t.reason}</span>}
            </span>
            <Button size="sm" variant="secondary" disabled={del.isPending} aria-label={`Remove time off starting ${formatDateTime(t.starts_at, timeZone)}`} onClick={() => del.mutate(t.id)}>
              Remove
            </Button>
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-2" noValidate>
        <Field label="Away from" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Field label="Back at" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
        <div className="sm:col-span-2"><Field label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} /></div>
        <div><Button type="submit" variant="secondary" loading={add.isPending}>Add time off</Button></div>
      </form>
      <div className="mt-3 space-y-2">
        {problem && <Alert tone="error">{problem}</Alert>}
        {add.error && <Alert tone="error">{errorMessage(add.error)}</Alert>}
        {del.error && <Alert tone="error">{errorMessage(del.error)}</Alert>}
      </div>
    </div>
  );
}
