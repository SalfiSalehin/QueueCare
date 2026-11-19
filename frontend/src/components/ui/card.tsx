import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs", className)} {...props} />;
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <h1 className="font-display text-3xl font-semibold tracking-tight text-ink">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
    </div>
  );
}

/** A single headline number with a label, for summary strips. */
export function StatTile({ label, value, tone = "light" }: { label: string; value: number | string; tone?: "light" | "dark" }) {
  return (
    <div className={cn("rounded-2xl px-5 py-4", tone === "dark" ? "bg-ink text-white" : "bg-white ring-1 ring-slate-200/80")}>
      <p className={cn("text-sm", tone === "dark" ? "text-teal-100" : "text-slate-500")}>{label}</p>
      <p className="tnum mt-1 font-display text-3xl font-semibold leading-none">{value}</p>
    </div>
  );
}
