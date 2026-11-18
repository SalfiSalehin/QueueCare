"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Alert } from "@/components/ui/feedback";
import { errorMessage, keys } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { registerSchema, type RegisterValues } from "@/lib/auth-schemas";
import { authService } from "@/services/auth";

export default function RegisterPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<RegisterValues>({ resolver: zodResolver(registerSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await authService.register(values);
      await authService.login(values.email, values.password);
      await qc.invalidateQueries({ queryKey: keys.me });
      router.replace("/app/clinics");
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError("Too many sign-ups from this network. Please try again later.");
      else setError(errorMessage(e));
    }
  });

  return (
    <AuthShell title="Create your account" subtitle="Use a made-up name and an address like demo@example.com. This is a demonstration.">
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <Field label="Full name" autoComplete="name" error={errors.full_name?.message} {...register("full_name")} />
        <Field label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
        <Field
          label="Password" type="password" autoComplete="new-password" error={errors.password?.message}
          hint="At least 12 characters. Common passwords are rejected."
          {...register("password")}
        />
        <Button type="submit" loading={isSubmitting} className="w-full">Create account</Button>
      </form>
      <p className="mt-6 text-sm text-slate-600">
        Already registered? <Link href="/login" className="font-medium text-teal-800 underline">Sign in</Link>
      </p>
    </AuthShell>
  );
}
