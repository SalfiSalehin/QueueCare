import type { CSSProperties } from "react";
import { cn } from "@/lib/cn";

const row = (i: number) => ({ "--i": i } as CSSProperties);

/** Decorative illustration of the staff board and a patient's phone. It shows no real data and carries no claims. */
export function ProductMockup({ className, phoneOnly = false }: { className?: string; phoneOnly?: boolean }) {
  return (
    <div
      role="img"
      aria-label="Illustration: the staff queue board and a patient's phone showing a queue token"
      className={cn("relative mx-auto w-full", phoneOnly ? "max-w-[15rem]" : "max-w-xl", className)}
    >
      {!phoneOnly && (
        <div className="overflow-hidden rounded-2xl bg-white shadow-[0_30px_80px_-20px_rgba(0,0,0,0.55)] ring-1 ring-white/10">
          <div className="flex items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-4 py-3">
            <span className="h-2.5 w-2.5 rounded-full bg-slate-300" /><span className="h-2.5 w-2.5 rounded-full bg-slate-300" /><span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
            <span className="ml-3 h-4 w-40 rounded-full bg-slate-200/80" />
          </div>
          <div className="grid gap-4 p-5 sm:grid-cols-[1.1fr_1fr]">
            <div className="rounded-xl bg-ink p-4 text-white">
              <p className="text-xs text-teal-100">With the doctor</p>
              <p className="tnum mt-1 font-display text-4xl font-semibold leading-none">G-014</p>
              <span className="mt-3 inline-block rounded-full bg-ticket px-2.5 py-0.5 text-[11px] font-semibold text-ink">in consultation</span>
              <div className="mt-4 h-8 w-24 rounded-lg bg-teal-600/90" />
            </div>
            <ul className="space-y-2">
              {["G-015", "G-016", "G-017"].map((t, i) => (
                <li key={t} style={row(i + 1)} className="settle flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2.5">
                  <span className="tnum font-display text-base font-semibold text-ink">{t}</span>
                  <span className="h-6 w-12 rounded-md bg-teal-700/90" />
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div
        style={row(4)}
        className={cn(
          "settle w-[15rem] rounded-[2rem] bg-ink p-2 shadow-[0_30px_70px_-15px_rgba(0,0,0,0.6)] ring-1 ring-white/15",
          phoneOnly ? "mx-auto" : "absolute -bottom-10 -left-2 sm:-left-10",
        )}
      >
        <div className="rounded-[1.6rem] bg-white px-5 pb-6 pt-5">
          <div className="mx-auto mb-4 h-1.5 w-14 rounded-full bg-slate-200" />
          <p className="text-xs text-slate-500">Your token</p>
          <p className="tnum font-display text-5xl font-semibold leading-none tracking-tight text-ink">G-017</p>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-xl bg-mint px-3 py-2"><p className="text-slate-500">Ahead of you</p><p className="text-base font-semibold text-ink">2 people</p></div>
            <div className="rounded-xl bg-slate-100 px-3 py-2"><p className="text-slate-500">Estimate</p><p className="text-base font-semibold text-ink">~10 min</p></div>
          </div>
          <p className="mt-3 text-[11px] leading-snug text-slate-500">From a simple rule, not a model. A guide, not a promise.</p>
        </div>
      </div>
    </div>
  );
}
