import type { LiveStatus } from "@/lib/realtime";
import { cn } from "@/lib/cn";

const TEXT: Record<LiveStatus, string> = {
  live: "Live updates on",
  connecting: "Connecting…",
  offline: "Live updates off; refreshing every few seconds",
};

export function LiveBadge({ status }: { status: LiveStatus }) {
  return (
    <p role="status" className="flex items-center gap-2 text-xs text-slate-600">
      <span aria-hidden className={cn("h-2 w-2 rounded-full", status === "live" ? "bg-emerald-500" : status === "connecting" ? "bg-amber-400" : "bg-slate-400")} />
      {TEXT[status]}
    </p>
  );
}
