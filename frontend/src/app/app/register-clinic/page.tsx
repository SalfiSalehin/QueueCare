"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, PageTitle } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Field } from "@/components/ui/field";
import { errorMessage, useRegisterClinic } from "@/hooks/queries";
import {
  defaultTimeZone, NAME_MAX, registrationBody, slugFromName, SLUG_MAX, validateRegistration, type RegistrationErrors,
} from "@/lib/register-clinic";

const ZONES = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];

export default function RegisterClinic() {
  const register = useRegisterClinic();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [timezone, setTimezone] = useState(defaultTimeZone);
  const [errors, setErrors] = useState<RegistrationErrors>({});
  const [submitted, setSubmitted] = useState<string | null>(null);

  const changeName = (value: string) => {
    setName(value);
    if (!slugEdited) setSlug(slugFromName(value));      // the address follows the name until the person types their own
  };
  const changeSlug = (value: string) => {
    setSlug(value.toLowerCase());
    setSlugEdited(value !== "");                          // clearing it hands control back to the name
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const form = { name, slug, timezone };
    const found = validateRegistration(form);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    // mutateAsync: a failure is shown through `register.error`, so the rejected promise is swallowed here.
    register.mutateAsync(registrationBody(form)).then((clinic) => setSubmitted(clinic.name), () => undefined);
  };

  const another = () => {
    register.reset();
    setName(""); setSlug(""); setSlugEdited(false); setErrors({}); setSubmitted(null);
  };

  if (submitted !== null) {
    return (
      <>
        <PageTitle title="Register a clinic" />
        <Card className="max-w-2xl">
          <Alert tone="success">
            <strong>{submitted}</strong> has been submitted. A platform administrator must approve it before patients can find it. You are its clinic admin,
            and you will see it under My clinics, marked as waiting for approval, until then.
          </Alert>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link href="/app" className="inline-flex rounded-xl bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-teal-800">Go to My clinics</Link>
            <Button variant="secondary" onClick={another}>Register another clinic</Button>
          </div>
        </Card>
      </>
    );
  }

  return (
    <>
      <PageTitle title="Register a clinic" subtitle="A platform administrator reviews every new clinic before patients can find it. You become its clinic admin." />
      <Card className="max-w-2xl">
        <form onSubmit={submit} noValidate className="grid gap-4">
          <Field
            label="Clinic name" value={name} onChange={(e) => changeName(e.target.value)} error={errors.name}
            maxLength={NAME_MAX} autoComplete="organization" placeholder="Lakeside Family Clinic"
          />
          <Field
            label="Clinic web address name" value={slug} onChange={(e) => changeSlug(e.target.value)} error={errors.slug}
            maxLength={SLUG_MAX} autoComplete="off" spellCheck={false} placeholder="lakeside-family-clinic"
            hint="Lowercase letters, digits and hyphens. It is part of how the clinic is found in a search, and it must not be used by another clinic."
          />
          <div>
            <Field
              label="Time zone" value={timezone} onChange={(e) => setTimezone(e.target.value)} error={errors.timezone}
              list="register-time-zones" autoComplete="off"
              hint="Doctors' weekly hours are read in this time zone. You can change it later in the clinic's setup."
            />
            <datalist id="register-time-zones">{ZONES.map((z) => <option key={z} value={z} />)}</datalist>
          </div>
          {register.error && <Alert tone="error">{errorMessage(register.error)}</Alert>}
          <div><Button type="submit" loading={register.isPending}>Register clinic</Button></div>
        </form>
      </Card>
    </>
  );
}
