import { cn } from "@/lib/cn";

export function initials(name: string): string {
  return name.replace(/^(dr\.?|mr\.?|ms\.?|mrs\.?)\s+/i, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";
}

/** Round monogram. Decorative: the name is always written next to it. */
export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span aria-hidden className={cn("grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-mint font-display text-base font-semibold text-teal-900", className)}>
      {initials(name)}
    </span>
  );
}
