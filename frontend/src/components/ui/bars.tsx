import { cn } from "@/lib/cn";

/** One horizontal bar with a label on the left and the value on the right. Width is a percentage of the largest bar. */
export function BarRow({ label, value, width, tone = "teal" }: { label: string; value: string; width: number; tone?: "teal" | "amber" }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-3 text-sm sm:grid-cols-[8rem_1fr_auto]">
      <span className="truncate text-slate-600">{label}</span>
      <span className="h-3 overflow-hidden rounded-full bg-slate-100" aria-hidden>
        <span className={cn("block h-full rounded-full", tone === "teal" ? "bg-teal-600" : "bg-ticket")} style={{ width: `${width}%` }} />
      </span>
      <span className="tnum min-w-[5.5rem] text-right font-medium text-slate-800">{value}</span>
    </div>
  );
}
