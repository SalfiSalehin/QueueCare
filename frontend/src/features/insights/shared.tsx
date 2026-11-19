import type { ReactNode } from "react";
import { Alert, Spinner } from "@/components/ui/feedback";
import { errorMessage } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import type { Tone } from "@/lib/insights";

export function Panel({ title, subtitle, children, className }: { title: string; subtitle?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-3xl bg-white p-6 shadow-xs ring-1 ring-slate-200/80", className)}>
      <h2 className="font-display text-xl font-semibold text-ink">{title}</h2>
      {subtitle && <p className="mt-1 max-w-2xl text-sm text-slate-600">{subtitle}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

/** Loading and error states for a query; renders children only when there is data. */
export function QueryBoundary({ isLoading, error, children }: { isLoading: boolean; error: unknown; children: ReactNode }) {
  if (isLoading) return <Spinner />;
  if (error) return <Alert tone="error">{errorMessage(error)}</Alert>;
  return <>{children}</>;
}

const TONES: Record<Tone, string> = {
  good: "bg-emerald-100 text-emerald-900", watch: "bg-amber-100 text-amber-900",
  bad: "bg-red-100 text-red-900", neutral: "bg-slate-200 text-slate-700",
};

export function ToneBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={cn("inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", TONES[tone])}>{children}</span>;
}

export const words = (s: string): string => s.replace(/_/g, " ").toLowerCase();
