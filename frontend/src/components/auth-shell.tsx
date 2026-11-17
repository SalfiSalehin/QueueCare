import type { ReactNode } from "react";
import { DemoBanner } from "@/components/demo-banner";
import { Logo } from "@/components/logo";
import { ProductMockup } from "@/components/product-mockup";

/** Split layout for sign-in and registration: a dark panel showing the product on the left, the form on the right. */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <>
      <DemoBanner />
      <div className="grid min-h-[calc(100vh-2rem)] lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <aside className="relative hidden flex-col justify-between overflow-hidden bg-ink p-10 text-white lg:flex">
          <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-teal-700/40 blur-3xl" />
          <Logo tone="light" />
          <div className="relative space-y-8">
            <h2 className="max-w-sm font-display text-4xl font-semibold leading-tight tracking-tight">
              Know where you stand in line.
            </h2>
            <ProductMockup phoneOnly className="max-w-[15rem]" />
          </div>
          <p className="relative text-xs text-teal-100/80">Portfolio demonstration. Synthetic data only.</p>
        </aside>
        <main id="main" className="flex items-center justify-center px-5 py-10">
          <div className="w-full max-w-sm">
            <div className="mb-8 lg:hidden"><Logo /></div>
            <h1 className="font-display text-3xl font-semibold tracking-tight text-ink">{title}</h1>
            {subtitle && <p className="mt-2 text-sm text-slate-600">{subtitle}</p>}
            <div className="mt-8">{children}</div>
          </div>
        </main>
      </div>
    </>
  );
}
