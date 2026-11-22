import { showDemoBanner } from "@/lib/demo";

/** The synthetic-data notice. Set NEXT_PUBLIC_DEMO_MODE=false to hide it (for screenshots and recordings); it is on by default. */
export function DemoBanner() {
  if (!showDemoBanner(process.env.NEXT_PUBLIC_DEMO_MODE)) return null;
  return (
    <div className="bg-amber-100 px-4 py-1.5 text-center text-xs text-amber-950">
      Demonstration system: synthetic data only. Do not enter real personal or medical information.
    </div>
  );
}
