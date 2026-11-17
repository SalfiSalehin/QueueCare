import Link from "next/link";
import { cn } from "@/lib/cn";

/** A queue-ticket stub: rounded body with a notch on each side. */
export function TicketMark({ className }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 28 28" className={cn("h-7 w-7", className)}>
      <path
        d="M6 3h16a3 3 0 0 1 3 3v4a3 3 0 0 0 0 6v6a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3v-6a3 3 0 0 0 0-6V6a3 3 0 0 1 3-3Z"
        className="fill-teal-700"
      />
      <path d="M10 10.5h8M10 14h8M10 17.5h4.5" className="stroke-white" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ href = "/", tone = "dark" }: { href?: string; tone?: "dark" | "light" }) {
  return (
    <Link href={href} className={cn("flex items-center gap-2 font-display text-lg font-semibold tracking-tight", tone === "light" ? "text-white" : "text-ink")}>
      <TicketMark className={tone === "light" ? "[&_path:first-child]:fill-ticket [&_path:last-child]:stroke-ink" : undefined} />
      QueueCare
    </Link>
  );
}
