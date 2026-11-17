import type { CSSProperties } from "react";
import { cn } from "@/lib/cn";

/** A picture of what the product shows, with invented tokens. It never calls the API and says so on the card. */
export function SampleBoard({ className }: { className?: string }) {
  const waiting = [
    { token: "G-015", ahead: 0, note: "next" },
    { token: "G-016", ahead: 1, note: "" },
    { token: "G-017", ahead: 2, note: "you" },
  ];
  return (
    <figure className={cn("w-full max-w-md rounded-3xl bg-white p-6 shadow-lift ring-1 ring-ink/5", className)}>
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>Dr Rahman, Room 2</span>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-600">Sample data</span>
      </div>

      <div className="settle mt-4 flex items-end justify-between rounded-2xl bg-ink px-5 py-4 text-white" style={{ "--i": 0 } as CSSProperties}>
        <div>
          <p className="text-sm text-teal-100">Now serving</p>
          <p className="tnum font-display text-5xl font-semibold leading-none tracking-tight">G-014</p>
        </div>
        <span className="mb-1 rounded-full bg-ticket px-3 py-1 text-xs font-semibold text-ink">In consultation</span>
      </div>

      <ul className="mt-3 space-y-2" aria-label="Waiting">
        {waiting.map((w, i) => (
          <li
            key={w.token}
            style={{ "--i": i + 1 } as CSSProperties}
            className={cn("settle flex items-center justify-between rounded-xl px-4 py-3", w.note === "you" ? "bg-mint ring-1 ring-teal-700/30" : "bg-slate-50")}
          >
            <span className="tnum font-display text-xl font-semibold">{w.token}</span>
            <span className="text-sm text-slate-600">
              {w.note === "you" ? "Your token · " : ""}
              {w.ahead === 0 ? "you are next after this visit" : `${w.ahead} ${w.ahead === 1 ? "person" : "people"} ahead`}
            </span>
          </li>
        ))}
      </ul>

      <figcaption className="mt-4 text-xs leading-relaxed text-slate-500">
        Illustration with invented tokens. In the app a patient sees their own token, how many people are ahead, and an estimate
        that says whether it came from a model or a simple rule.
      </figcaption>
    </figure>
  );
}
