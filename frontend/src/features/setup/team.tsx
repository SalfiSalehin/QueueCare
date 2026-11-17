"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Spinner } from "@/components/ui/feedback";
import { Field, SelectField } from "@/components/ui/field";
import { errorMessage, useMe } from "@/hooks/queries";
import { useAddMember, useMembers, useSetMemberActive } from "@/hooks/setup";
import { plural } from "@/lib/format";
import type { ClinicRole } from "@/types/api";

const STAFF_ROLES: { value: ClinicRole; label: string }[] = [
  { value: "RECEPTIONIST", label: "Receptionist" },
  { value: "DOCTOR", label: "Doctor" },
  { value: "CLINIC_ADMIN", label: "Clinic administrator" },
];
const roleLabel = (r: string) => STAFF_ROLES.find((x) => x.value === r)?.label ?? r.replace(/_/g, " ").toLowerCase();

export function TeamSection({ clinicId }: { clinicId: string }) {
  const members = useMembers(clinicId);
  const me = useMe();
  const add = useAddMember(clinicId);
  const setActive = useSetMemberActive(clinicId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<ClinicRole>("RECEPTIONIST");
  const [added, setAdded] = useState<string | null>(null);
  const all = members.data ?? [];
  const staff = all.filter((m) => m.role !== "PATIENT");
  const patients = new Set(all.filter((m) => m.role === "PATIENT").map((m) => m.user_id)).size;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setAdded(null);
    add.mutate({ email, role }, { onSuccess: (m) => { setAdded(`${m.full_name} is now ${roleLabel(m.role).toLowerCase()}.`); setEmail(""); } });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card>
        <h2 className="font-display text-xl font-semibold text-ink">Team</h2>
        <p className="text-sm text-slate-600">{plural(patients, "patient")} joined this clinic. Staff are listed below.</p>
        {members.isLoading && <div className="mt-4"><Spinner /></div>}
        {members.isError && <Alert tone="error" className="mt-4">{errorMessage(members.error)}</Alert>}
        <ul className="mt-2 divide-y divide-slate-100">
          {staff.map((m) => {
            const self = m.user_id === me.data?.user.id;
            return (
              <li key={m.membership_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <p className="font-medium text-ink">{m.full_name}{self && <span className="text-slate-500"> (you)</span>}</p>
                  <p className="text-xs text-slate-600">{m.email} &middot; {roleLabel(m.role)}{!m.is_active && " · deactivated"}</p>
                </div>
                <Button
                  size="sm" variant={m.is_active ? "danger" : "secondary"} disabled={self} loading={setActive.isPending}
                  title={self ? "You cannot deactivate your own access" : undefined}
                  aria-label={`${m.is_active ? "Deactivate" : "Activate"} ${m.full_name} as ${roleLabel(m.role).toLowerCase()}`}
                  onClick={() => setActive.mutate({ membershipId: m.membership_id, isActive: !m.is_active })}
                >
                  {m.is_active ? "Deactivate" : "Activate"}
                </Button>
              </li>
            );
          })}
        </ul>
        {setActive.error && <Alert tone="error" className="mt-3">{errorMessage(setActive.error)}</Alert>}
      </Card>
      <Card>
        <h2 className="font-display text-xl font-semibold text-ink">Add a team member</h2>
        <p className="mt-1 text-sm text-slate-600">They need a QueueCare account first. Ask them to register, then add their email here.</p>
        <form onSubmit={submit} className="mt-4 space-y-3">
          <Field label="Their email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="off" />
          <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value as ClinicRole)}>
            {STAFF_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </SelectField>
          {add.error && <Alert tone="error">{errorMessage(add.error)}</Alert>}
          {added && <Alert tone="success">{added}</Alert>}
          <Button type="submit" loading={add.isPending} disabled={email.trim().length < 3}>Add to team</Button>
        </form>
      </Card>
    </div>
  );
}
