"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/feedback";
import { Field, SelectField } from "@/components/ui/field";
import { errorMessage } from "@/hooks/queries";
import { useUpdateDoctor } from "@/hooks/setup";
import { doctorChanges, validateDoctor } from "@/lib/setup";
import type { Department, Doctor } from "@/types/api";

/** Edit a doctor's name, department and appointment timing. Only what changed is sent. */
export function DoctorEditForm({ clinicId, doctor, departments, onDone }: {
  clinicId: string; doctor: Doctor; departments: Department[]; onDone: () => void;
}) {
  const update = useUpdateDoctor(clinicId);
  const [name, setName] = useState(doctor.display_name);
  const [dept, setDept] = useState(doctor.department_id);
  const [slot, setSlot] = useState(String(doctor.default_slot_minutes));
  const [buffer, setBuffer] = useState(String(doctor.buffer_minutes));
  const [problem, setProblem] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const form = { name, departmentId: dept, slot: Number(slot), buffer: Number(buffer) };
    const bad = validateDoctor(form.name, form.departmentId, form.slot, form.buffer);
    setProblem(bad);
    if (bad) return;
    const body = doctorChanges(doctor, form);
    if (Object.keys(body).length === 0) { onDone(); return; }
    update.mutate({ doctorId: doctor.id, body }, { onSuccess: onDone });
  };

  return (
    <form onSubmit={submit} noValidate aria-label={`Edit details for ${doctor.display_name}`} className="mt-4 grid gap-3 rounded-2xl bg-slate-50 p-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><Field label="Doctor name" value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div className="sm:col-span-2">
        <SelectField label="Department" value={dept} onChange={(e) => setDept(e.target.value)}>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </SelectField>
      </div>
      <Field label="Appointment length (minutes)" type="number" inputMode="numeric" min={5} max={240} value={slot} onChange={(e) => setSlot(e.target.value)} />
      <Field label="Gap between appointments (minutes)" type="number" inputMode="numeric" min={0} max={120} value={buffer} onChange={(e) => setBuffer(e.target.value)} />
      <p className="text-xs text-slate-600 sm:col-span-2">
        New lengths apply to times patients book from now on. Appointments already booked keep the time they were given.
      </p>
      {problem && <div className="sm:col-span-2"><Alert tone="error">{problem}</Alert></div>}
      {update.error && <div className="sm:col-span-2"><Alert tone="error">{errorMessage(update.error)}</Alert></div>}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" size="sm" loading={update.isPending}>Save changes</Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}
