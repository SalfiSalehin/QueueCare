"use client";

import { useState, type FormEvent } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, EmptyState, Spinner, StatusBadge } from "@/components/ui/feedback";
import { Field, SelectField } from "@/components/ui/field";
import { DoctorEditForm } from "@/features/setup/doctor-edit";
import { ScheduleEditor, TimeOffEditor } from "@/features/setup/schedule-editor";
import { errorMessage } from "@/hooks/queries";
import { useAllDoctors, useCreateDoctor, useDepartments, useMembers, useSetDoctorActive } from "@/hooks/setup";
import { validateDoctor } from "@/lib/setup";
import type { Department, Doctor } from "@/types/api";

function DoctorRow({ clinicId, timeZone, doctor, department, departments }: {
  clinicId: string; timeZone: string; doctor: Doctor; department?: Department; departments: Department[];
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const setActive = useSetDoctorActive(clinicId);
  const panelId = `doctor-panel-${doctor.id}`;
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar name={doctor.display_name} />
          <div>
            <p className="font-medium text-ink">{doctor.display_name}</p>
            <p className="text-xs text-slate-600">
              {department?.name ?? "Unknown department"} &middot; {doctor.default_slot_minutes} min appointments, {doctor.buffer_minutes} min gap
              {doctor.has_account ? " · has a login" : " · no login linked"}
            </p>
          </div>
          {doctor.is_active ? <StatusBadge status={doctor.status} /> : <span className="rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-medium text-slate-700">not accepting bookings</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" aria-expanded={editing} aria-label={`Edit details for ${doctor.display_name}`} onClick={() => setEditing((e) => !e)}>
            {editing ? "Close editor" : "Edit details"}
          </Button>
          <Button size="sm" variant="secondary" aria-expanded={open} aria-controls={panelId} aria-label={`Hours and time off for ${doctor.display_name}`} onClick={() => setOpen((o) => !o)}>
            {open ? "Hide hours" : "Hours and time off"}
          </Button>
          <Button
            size="sm" variant={doctor.is_active ? "danger" : "secondary"} loading={setActive.isPending}
            aria-label={`${doctor.is_active ? "Deactivate" : "Activate"} ${doctor.display_name}`}
            onClick={() => setActive.mutate({ doctorId: doctor.id, isActive: !doctor.is_active })}
          >
            {doctor.is_active ? "Deactivate" : "Activate"}
          </Button>
        </div>
      </div>
      {setActive.error && <Alert tone="error" className="mt-3">{errorMessage(setActive.error)}</Alert>}
      {editing && <DoctorEditForm clinicId={clinicId} doctor={doctor} departments={departments} onDone={() => setEditing(false)} />}
      {open && (
        <div id={panelId} className="mt-4 grid gap-8 rounded-2xl bg-slate-50 p-4">
          <ScheduleEditor clinicId={clinicId} doctorId={doctor.id} timeZone={timeZone} />
          <TimeOffEditor clinicId={clinicId} doctorId={doctor.id} timeZone={timeZone} />
        </div>
      )}
    </li>
  );
}

function AddDoctor({ clinicId, departments }: { clinicId: string; departments: Department[] }) {
  const members = useMembers(clinicId);
  const create = useCreateDoctor(clinicId);
  const [name, setName] = useState("");
  const [dept, setDept] = useState("");
  const [slot, setSlot] = useState("15");
  const [buffer, setBuffer] = useState("5");
  const [login, setLogin] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const chosenDept = dept || departments[0]?.id || "";
  const doctorLogins = (members.data ?? []).filter((m) => m.role === "DOCTOR" && m.is_active);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setAdded(null);
    const bad = validateDoctor(name, chosenDept, Number(slot), Number(buffer));
    setProblem(bad);
    if (bad) return;
    create.mutate(
      { display_name: name.trim(), department_id: chosenDept, default_slot_minutes: Number(slot), buffer_minutes: Number(buffer), user_id: login || null },
      { onSuccess: (d) => { setAdded(`${d.display_name} was added. Open Hours and time off to set when they work.`); setName(""); setLogin(""); } },
    );
  };

  return (
    <Card>
      <h2 className="font-display text-xl font-semibold text-ink">Add a doctor</h2>
      {departments.length === 0 ? (
        <p className="mt-3 text-sm text-slate-600">Add a department first (Departments tab). Every doctor belongs to one.</p>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-3" noValidate>
          <Field label="Doctor name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Dr Synthetic" />
          <SelectField label="Department" value={chosenDept} onChange={(e) => setDept(e.target.value)}>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </SelectField>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Appointment length (minutes)" type="number" inputMode="numeric" min={5} max={240} value={slot} onChange={(e) => setSlot(e.target.value)} />
            <Field label="Gap between appointments (minutes)" type="number" inputMode="numeric" min={0} max={120} value={buffer} onChange={(e) => setBuffer(e.target.value)} />
          </div>
          <SelectField label="Linked login (optional)" value={login} onChange={(e) => setLogin(e.target.value)} hint="Lets this person sign in and run their own queue. Add them to the team as a doctor first.">
            <option value="">No login</option>
            {doctorLogins.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name} ({m.email})</option>)}
          </SelectField>
          {problem && <Alert tone="error">{problem}</Alert>}
          {create.error && <Alert tone="error">{errorMessage(create.error)}</Alert>}
          {added && <Alert tone="success">{added}</Alert>}
          <Button type="submit" loading={create.isPending}>Add doctor</Button>
        </form>
      )}
    </Card>
  );
}

export function DoctorsSection({ clinicId, timeZone }: { clinicId: string; timeZone: string }) {
  const doctors = useAllDoctors(clinicId);
  const departments = useDepartments(clinicId);
  const depts = departments.data?.items ?? [];
  const byId = new Map(depts.map((d) => [d.id, d]));
  const items = doctors.data?.items ?? [];
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card>
        <h2 className="font-display text-xl font-semibold text-ink">Doctors</h2>
        <p className="text-sm text-slate-600">Patients can book a doctor who is active and has weekly hours.</p>
        {doctors.isLoading && <div className="mt-4"><Spinner /></div>}
        {doctors.isError && <Alert tone="error" className="mt-4">{errorMessage(doctors.error)}</Alert>}
        {doctors.data && items.length === 0 && <div className="mt-4"><EmptyState title="No doctors yet">Add a department, then add your first doctor.</EmptyState></div>}
        <ul className="mt-2 divide-y divide-slate-100">
          {items.map((d) => <DoctorRow key={d.id} clinicId={clinicId} timeZone={timeZone} doctor={d} department={byId.get(d.department_id)} departments={depts} />)}
        </ul>
      </Card>
      <AddDoctor clinicId={clinicId} departments={depts} />
    </div>
  );
}
