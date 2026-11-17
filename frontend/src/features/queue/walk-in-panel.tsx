"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Alert } from "@/components/ui/feedback";
import { errorMessage } from "@/hooks/queries";
import { useCreatePatient, usePatientSearch, useWalkIn } from "@/hooks/staff";
import type { Doctor } from "@/types/api";

/** Put a patient without an appointment into a doctor's queue. Search existing patients first; register a new one if needed. */
export function WalkInPanel({ clinicId, doctors }: { clinicId: string; doctors: Doctor[] }) {
  const [doctorId, setDoctorId] = useState("");
  const [text, setText] = useState("");
  const [newName, setNewName] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [added, setAdded] = useState<string | null>(null);
  const search = usePatientSearch(clinicId, text);
  const walkIn = useWalkIn(clinicId);
  const createPatient = useCreatePatient(clinicId);
  const chosen = doctorId || doctors[0]?.id || "";
  const error = walkIn.error ?? createPatient.error ?? search.error;

  const add = (patientId: string, name: string) => {
    setAdded(null);
    walkIn.mutate({ doctorId: chosen, patientId }, { onSuccess: (t) => setAdded(`${name} is in the queue as ${t.token_label}.`) });
  };

  const register = (e: FormEvent) => {
    e.preventDefault();
    createPatient.mutate(
      { fullName: newName.trim(), phone: newPhone.trim() || null },
      { onSuccess: (p) => { add(p.id, p.full_name); setNewName(""); setNewPhone(""); } },
    );
  };

  return (
    <Card>
      <h2 className="font-display text-xl font-semibold text-ink">Add a walk-in</h2>
      <p className="text-sm text-slate-600">For patients who arrive without an appointment.</p>
      <div className="mt-4 space-y-4">
        <div className="space-y-1">
          <label htmlFor="walkin-doctor" className="block text-sm font-medium text-slate-800">Doctor</label>
          <select
            id="walkin-doctor" value={chosen} onChange={(e) => setDoctorId(e.target.value)}
            className="block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm"
          >
            {doctors.map((d) => <option key={d.id} value={d.id}>{d.display_name}</option>)}
          </select>
        </div>
        <Field label="Find a patient" placeholder="Name or phone (at least 2 characters)" value={text} onChange={(e) => setText(e.target.value)} />
        {search.data && search.data.items.length === 0 && text.trim().length >= 2 && (
          <p className="text-sm text-slate-500">No patient found. Register them below.</p>
        )}
        <ul className="divide-y divide-slate-100">
          {search.data?.items.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 py-2">
              <span className="text-sm">{p.full_name}{p.phone && <span className="text-slate-500"> · {p.phone}</span>}</span>
              <Button size="sm" disabled={walkIn.isPending || !chosen} onClick={() => add(p.id, p.full_name)}>Add to queue</Button>
            </li>
          ))}
        </ul>
        <form onSubmit={register} className="space-y-3 border-t border-slate-100 pt-4">
          <p className="text-sm font-medium">New patient</p>
          <Field label="Full name" value={newName} onChange={(e) => setNewName(e.target.value)} required minLength={2} />
          <Field label="Phone (optional)" value={newPhone} onChange={(e) => setNewPhone(e.target.value)} inputMode="tel" />
          <Button type="submit" variant="secondary" disabled={!chosen || newName.trim().length < 2} loading={createPatient.isPending || walkIn.isPending}>
            Register and add to queue
          </Button>
        </form>
        {added && <Alert tone="success">{added}</Alert>}
        {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      </div>
    </Card>
  );
}
