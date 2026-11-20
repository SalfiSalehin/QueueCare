"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Spinner } from "@/components/ui/feedback";
import { Field, SelectField } from "@/components/ui/field";
import { errorMessage, useClinic } from "@/hooks/queries";
import { useUpdateClinic } from "@/hooks/setup";
import { clinicChanges, clinicFormFrom, validateClinic, type ClinicForm } from "@/lib/setup";
import type { ClinicDetail } from "@/types/api";

const COMMON_ZONES = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];

/** `done` lives in the parent: a successful save refreshes the clinic, which restarts this form, and would erase the message. */
function SettingsForm({ clinic, done, setDone }: { clinic: ClinicDetail; done: string | null; setDone: (message: string | null) => void }) {
  const update = useUpdateClinic(clinic.id);
  const saved = clinicFormFrom(clinic);
  const [name, setName] = useState(saved.name);
  const [timezone, setTimezone] = useState(saved.timezone);
  const [horizon, setHorizon] = useState(String(saved.bookingHorizonDays));
  const [notice, setNotice] = useState(String(saved.minNoticeMinutes));
  const [cutoff, setCutoff] = useState(String(saved.cancellationCutoffHours));
  const [policy, setPolicy] = useState(saved.queuePolicy);
  const [walkin, setWalkin] = useState(saved.walkinPriorityEnabled);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setDone(null);
    const form: ClinicForm = {
      name, timezone, bookingHorizonDays: Number(horizon), minNoticeMinutes: Number(notice),
      cancellationCutoffHours: Number(cutoff), queuePolicy: policy, walkinPriorityEnabled: walkin,
    };
    const bad = validateClinic(form);
    setProblem(bad);
    if (bad) return;
    const body = clinicChanges(clinic, form);
    if (Object.keys(body).length === 0) { setDone("Nothing to save: these are already the current settings."); return; }
    // mutateAsync, not a per-call onSuccess: the saved clinic restarts this form, and a callback tied to it could be dropped.
    // A failure is shown through `update.error`, so it is swallowed here.
    update.mutateAsync(body).then(() => setDone("Saved. The change applies to bookings and the queue from now on."), () => undefined);
  };

  return (
    <form onSubmit={submit} noValidate className="mt-4 grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><Field label="Clinic name" value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div className="sm:col-span-2">
        <Field
          label="Time zone" value={timezone} onChange={(e) => setTimezone(e.target.value)} list="clinic-time-zones" autoComplete="off"
          hint="Weekly hours are read in this time zone. If you change it, existing hours keep their clock times but move to the new zone, so check each doctor's hours afterwards. Time off already entered stays at the same moment."
        />
        <datalist id="clinic-time-zones">{COMMON_ZONES.map((z) => <option key={z} value={z} />)}</datalist>
      </div>
      <Field label="Patients can book up to (days ahead)" type="number" inputMode="numeric" min={1} max={365} value={horizon} onChange={(e) => setHorizon(e.target.value)} />
      <Field label="Minimum notice before an appointment (minutes)" type="number" inputMode="numeric" min={0} max={1440} value={notice} onChange={(e) => setNotice(e.target.value)} />
      <Field label="Patients can cancel or reschedule until (hours before)" type="number" inputMode="numeric" min={0} max={168} value={cutoff} onChange={(e) => setCutoff(e.target.value)}
        hint="After this point patients are asked to contact the clinic. Front desk staff are not limited by it." />
      <SelectField label="Queue order" value={policy} onChange={(e) => setPolicy(e.target.value as ClinicForm["queuePolicy"])}
        hint="Appointments first: booked patients are called in order of their appointment time, then walk-ins by arrival. First come, first served: everyone in order of arrival. In both, a patient marked urgent goes first.">
        <option value="APPOINTMENT_FIRST">Appointments first</option>
        <option value="FIFO">First come, first served</option>
      </SelectField>
      <label className="flex items-start gap-3 text-sm text-slate-800 sm:col-span-2">
        <input type="checkbox" className="mt-0.5 size-4" checked={walkin} onChange={(e) => setWalkin(e.target.checked)} />
        <span>Let front desk staff mark a walk-in as urgent</span>
      </label>
      {problem && <div className="sm:col-span-2"><Alert tone="error">{problem}</Alert></div>}
      {update.error && <div className="sm:col-span-2"><Alert tone="error">{errorMessage(update.error)}</Alert></div>}
      {done && <div className="sm:col-span-2"><Alert tone="success">{done}</Alert></div>}
      <div className="sm:col-span-2"><Button type="submit" loading={update.isPending}>Save settings</Button></div>
    </form>
  );
}

export function ClinicSettingsSection({ clinicId }: { clinicId: string }) {
  const clinic = useClinic(clinicId);
  const [done, setDone] = useState<string | null>(null);
  return (
    <Card className="max-w-3xl">
      <h2 className="font-display text-xl font-semibold text-ink">Clinic settings</h2>
      <p className="text-sm text-slate-600">The name patients see, the clinic's time zone and the booking and cancellation rules.</p>
      {clinic.isLoading && <div className="mt-4"><Spinner /></div>}
      {clinic.isError && <Alert tone="error" className="mt-4">{errorMessage(clinic.error)}</Alert>}
      {/* key: if the saved clinic changes elsewhere the form restarts from the saved values instead of showing stale ones. */}
      {clinic.data && <SettingsForm key={`${clinic.data.name}|${clinic.data.timezone}|${JSON.stringify(clinic.data.settings)}`} clinic={clinic.data} done={done} setDone={setDone} />}
    </Card>
  );
}
