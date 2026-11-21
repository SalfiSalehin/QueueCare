"use client";

import { Building2, LogOut, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { DemoBanner } from "@/components/demo-banner";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Alert, Spinner } from "@/components/ui/feedback";
import { useLogout, useMe } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { isPlatformAdmin } from "@/lib/platform";

const NAV = [
  { href: "/app", label: "My clinics", Icon: Building2, active: (p: string) => p === "/app" || p.startsWith("/app/c/") },
  { href: "/app/clinics", label: "Find a clinic", Icon: Search, active: (p: string) => p.startsWith("/app/clinics") },
];
const PLATFORM_NAV = { href: "/app/platform", label: "Platform", Icon: ShieldCheck, active: (p: string) => p.startsWith("/app/platform") };

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useMe();
  const logout = useLogout();
  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (unauthenticated) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthenticated, router, pathname]);

  if (me.isLoading || unauthenticated) {
    return <div className="grid min-h-screen place-items-center"><Spinner label="Checking your session" /></div>;
  }
  if (me.isError || !me.data) {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        <Alert tone="error">We could not reach the server. Check that the API is running, then reload.</Alert>
        <Button className="mt-4" variant="secondary" onClick={() => void me.refetch()}>Try again</Button>
      </div>
    );
  }

  const user = me.data.user;
  // Only platform administrators get the Platform link; the API refuses everyone else regardless.
  const nav = isPlatformAdmin(user) ? [...NAV, PLATFORM_NAV] : NAV;
  const signOut = () => logout.mutate(undefined, { onSettled: () => router.replace("/login") });

  return (
    <>
      <DemoBanner />
      <div className="lg:grid lg:min-h-[calc(100vh-2rem)] lg:grid-cols-[16rem_minmax(0,1fr)]">
        {/* Desktop sidebar */}
        <aside className="hidden flex-col bg-ink p-5 text-white lg:flex">
          <Logo href="/app" tone="light" />
          <nav aria-label="Main" className="mt-10 space-y-1">
            {nav.map(({ href, label, Icon, active }) => (
              <Link
                key={href} href={href} aria-current={active(pathname) ? "page" : undefined}
                className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                  active(pathname) ? "bg-white/10 text-white" : "text-teal-100/80 hover:bg-white/5 hover:text-white")}
              >
                <Icon aria-hidden className="h-[18px] w-[18px]" />{label}
              </Link>
            ))}
          </nav>
          <div className="mt-auto rounded-2xl bg-white/5 p-3">
            <div className="flex items-center gap-3">
              <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ticket text-sm font-semibold text-ink">{initials(user.full_name)}</span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{user.full_name}</p>
                <p className="truncate text-xs text-teal-100/70" title={user.email}>{user.email}</p>
              </div>
            </div>
            <button
              type="button" onClick={signOut} disabled={logout.isPending}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-xs font-medium text-teal-50 hover:bg-white/10 disabled:opacity-50"
            >
              <LogOut aria-hidden className="h-3.5 w-3.5" />Sign out
            </button>
          </div>
        </aside>

        {/* Mobile top bar */}
        <header className="bg-ink text-white lg:hidden">
          <div className="flex items-center justify-between px-4 py-3">
            <Logo href="/app" tone="light" />
            <button type="button" onClick={signOut} className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-medium hover:bg-white/10">Sign out</button>
          </div>
          <nav aria-label="Main" className="flex gap-1 px-3 pb-3 text-sm">
            {nav.map(({ href, label, active }) => (
              <Link key={href} href={href} aria-current={active(pathname) ? "page" : undefined}
                className={cn("rounded-lg px-3 py-1.5", active(pathname) ? "bg-white/15 font-medium" : "text-teal-100/80")}>{label}</Link>
            ))}
          </nav>
        </header>

        <main id="main" className="min-w-0 px-5 py-8 lg:px-10 lg:py-10">
          <div className="mx-auto max-w-5xl">{children}</div>
        </main>
      </div>
    </>
  );
}
