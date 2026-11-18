"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Alert } from "@/components/ui/feedback";
import { errorMessage, keys } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { loginSchema, type LoginValues } from "@/lib/auth-schemas";
import { safeNext } from "@/lib/redirect";
import { authService } from "@/services/auth";

function LoginForm() {
  const router = useRouter();
  const qc = useQueryClient();
  const next = safeNext(useSearchParams().get("next"));
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await authService.login(values.email, values.password);
      await qc.invalidateQueries({ queryKey: keys.me });
      router.replace(next);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 429 ? "Too many attempts. Please wait a few minutes and try again." : errorMessage(e));
    }
  });

  return (
    <>
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <Field label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
        <Field label="Password" type="password" autoComplete="current-password" error={errors.password?.message} {...register("password")} />
        <Button type="submit" loading={isSubmitting} className="w-full">Sign in</Button>
      </form>
      <p className="mt-6 text-sm text-slate-600">
        New here? <Link href="/register" className="font-medium text-teal-800 underline">Create an account</Link>
      </p>
    </>
  );
}

export default function LoginPage() {
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to see your appointments and your place in the queue.">
      <Suspense fallback={null}><LoginForm /></Suspense>
    </AuthShell>
  );
}
