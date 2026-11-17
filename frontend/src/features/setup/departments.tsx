"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, EmptyState, Spinner } from "@/components/ui/feedback";
import { Field } from "@/components/ui/field";
import { errorMessage } from "@/hooks/queries";
import { useCreateDepartment, useDepartments, useRenameDepartment } from "@/hooks/setup";
import { validateDepartment } from "@/lib/setup";
import type { Department } from "@/types/api";

function DepartmentRow({ clinicId, dept }: { clinicId: string; dept: Department }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(dept.name);
  const rename = useRenameDepartment(clinicId);
  const save = (e: FormEvent) => {
    e.preventDefault();
    rename.mutate({ departmentId: dept.id, name }, { onSuccess: () => setEditing(false) });
  };
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      {editing ? (
        <form onSubmit={save} className="flex flex-wrap items-end gap-2">
          <Field label="New name" value={name} onChange={(e) => setName(e.target.value)} minLength={2} maxLength={100} required />
          <Button type="submit" size="sm" loading={rename.isPending} disabled={name.trim().length < 2}>Save name</Button>
          <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setName(dept.name); }}>Cancel</Button>
          {rename.error && <Alert tone="error" className="w-full">{errorMessage(rename.error)}</Alert>}
        </form>
      ) : (
        <>
          <div>
            <p className="font-medium text-ink">{dept.name}</p>
            <p className="text-xs text-slate-600">Queue tokens start with <span className="font-semibold">{dept.queue_prefix}</span>, for example {dept.queue_prefix}-001</p>
          </div>
          <Button size="sm" variant="secondary" aria-label={`Rename ${dept.name}`} onClick={() => setEditing(true)}>Rename</Button>
        </>
      )}
    </li>
  );
}

export function DepartmentsSection({ clinicId }: { clinicId: string }) {
  const departments = useDepartments(clinicId);
  const create = useCreateDepartment(clinicId);
  const [name, setName] = useState("");
  const [prefix, setPrefix] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setAdded(null);
    const bad = validateDepartment(name, prefix);
    setProblem(bad);
    if (bad) return;
    create.mutate({ name, prefix }, { onSuccess: (d) => { setAdded(`${d.name} was added.`); setName(""); setPrefix(""); } });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card>
        <h2 className="font-display text-xl font-semibold text-ink">Departments</h2>
        <p className="text-sm text-slate-600">Each doctor belongs to one department. The prefix appears on that department&apos;s queue tokens and cannot be changed later.</p>
        {departments.isLoading && <div className="mt-4"><Spinner /></div>}
        {departments.isError && <Alert tone="error" className="mt-4">{errorMessage(departments.error)}</Alert>}
        {departments.data && departments.data.items.length === 0 && (
          <div className="mt-4"><EmptyState title="No departments yet">Add one on the right, then add doctors to it.</EmptyState></div>
        )}
        <ul className="mt-2 divide-y divide-slate-100">
          {departments.data?.items.map((d) => <DepartmentRow key={d.id} clinicId={clinicId} dept={d} />)}
        </ul>
      </Card>
      <Card>
        <h2 className="font-display text-xl font-semibold text-ink">Add a department</h2>
        <form onSubmit={submit} className="mt-4 space-y-3" noValidate>
          <Field label="Department name" value={name} onChange={(e) => setName(e.target.value)} placeholder="General Medicine" />
          <Field label="Queue prefix" value={prefix} onChange={(e) => setPrefix(e.target.value.toUpperCase())} maxLength={3} placeholder="G" hint="1 to 3 letters." />
          {problem && <Alert tone="error">{problem}</Alert>}
          {create.error && <Alert tone="error">{errorMessage(create.error)}</Alert>}
          {added && <Alert tone="success">{added}</Alert>}
          <Button type="submit" loading={create.isPending}>Add department</Button>
        </form>
      </Card>
    </div>
  );
}
