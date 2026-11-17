import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Alert({ tone = "info", children, className }: { tone?: "info" | "error" | "success" | "warning"; children: ReactNode; className?: string }) {
  const tones = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    error: "border-red-200 bg-red-50 text-red-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
  };
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cn("rounded-lg border px-4 py-3 text-sm", tones[tone], className)}>
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-slate-600">
      <span aria-hidden className="h-4 w-4 animate-spin rounded-full border-2 border-teal-700 border-t-transparent" />
      {label}…
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-3xl border border-dashed border-slate-300 bg-white/70 px-6 py-12 text-center">
      <p className="font-display text-lg font-semibold text-ink">{title}</p>
      {children && <div className="mt-2 text-sm text-slate-600">{children}</div>}
    </div>
  );
}

const BADGE: Record<string, string> = {
  CONFIRMED: "bg-teal-100 text-teal-900", PENDING: "bg-amber-100 text-amber-900", CHECKED_IN: "bg-sky-100 text-sky-900",
  IN_PROGRESS: "bg-sky-100 text-sky-900", COMPLETED: "bg-slate-200 text-slate-800", CANCELLED: "bg-slate-200 text-slate-600",
  NO_SHOW: "bg-red-100 text-red-900", WAITING: "bg-amber-100 text-amber-900", CALLED: "bg-emerald-100 text-emerald-900",
  IN_CONSULTATION: "bg-sky-100 text-sky-900", SKIPPED: "bg-slate-200 text-slate-700",
  AVAILABLE: "bg-emerald-100 text-emerald-900", BUSY: "bg-amber-100 text-amber-900", DELAYED: "bg-orange-100 text-orange-900",
  OFF_DUTY: "bg-slate-200 text-slate-700",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", BADGE[status] ?? "bg-slate-200 text-slate-800")}>
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />
      {status.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}
