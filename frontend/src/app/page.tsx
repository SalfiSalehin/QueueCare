import { CalendarCheck, Radio, ShieldCheck, Gauge, UsersRound } from "lucide-react";
import Link from "next/link";
import { DemoBanner } from "@/components/demo-banner";
import { Logo } from "@/components/logo";
import { ProductMockup } from "@/components/product-mockup";

const STEPS = [
  { title: "Book", text: "Choose a doctor and a time that is actually free. A slot taken a second ago shows you other doctors who have one." },
  { title: "Check in", text: "Tell the front desk you have arrived. They check you in and you get a queue token." },
  { title: "Follow your place", text: "See how many people are ahead of you and an estimate of the wait, then go in when you are called." },
];

export default function Landing() {
  return (
    <>
      <DemoBanner />

      <div className="relative overflow-hidden bg-ink text-white">
        <div aria-hidden className="pointer-events-none absolute -left-40 top-0 h-[28rem] w-[28rem] rounded-full bg-teal-600/30 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -right-32 bottom-0 h-[24rem] w-[24rem] rounded-full bg-ticket/10 blur-3xl" />
        <header className="relative mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
          <Logo tone="light" />
          <nav aria-label="Account" className="flex items-center gap-2 text-sm font-medium">
            <Link href="/login" className="rounded-xl px-4 py-2.5 text-teal-50 hover:bg-white/10">Sign in</Link>
            <Link href="/register" className="rounded-xl bg-white px-4 py-2.5 text-ink hover:bg-teal-50">Create account</Link>
          </nav>
        </header>

        <main id="main">
          <section className="relative mx-auto grid max-w-6xl items-center gap-16 px-5 pb-28 pt-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:pt-20">
            <div>
              <h1 className="max-w-xl font-display text-5xl font-semibold leading-[1.02] tracking-tight sm:text-6xl lg:text-7xl">
                Know where you stand in line.
              </h1>
              <p className="mt-7 max-w-md text-lg leading-relaxed text-teal-50/85">
                Book a time with your clinic, check in at the front desk, then follow your place in the queue with
                an honest estimate of the wait.
              </p>
              <div className="mt-10 flex flex-wrap gap-3">
                <Link href="/register" className="rounded-xl bg-ticket px-7 py-3.5 font-semibold text-ink shadow-lg shadow-black/20 hover:brightness-95">Create an account</Link>
                <Link href="/login" className="rounded-xl border border-white/25 px-7 py-3.5 font-semibold text-white hover:bg-white/10">Sign in</Link>
              </div>
            </div>
            <div className="pb-10 lg:pb-0">
              <ProductMockup />
            </div>
          </section>
        </main>
      </div>

      <section aria-labelledby="features" className="mx-auto max-w-6xl px-5 py-24">
        <h2 id="features" className="max-w-2xl font-display text-4xl font-semibold tracking-tight text-ink">
          Everything a waiting room needs, in one place.
        </h2>
        <div className="mt-12 grid gap-4 md:grid-cols-6">
          <div className="rounded-3xl bg-white p-8 shadow-lift ring-1 ring-ink/5 md:col-span-4">
            <CalendarCheck aria-hidden className="h-7 w-7 text-teal-700" />
            <h3 className="mt-5 font-display text-2xl font-semibold text-ink">Booking that cannot double-book</h3>
            <p className="mt-3 max-w-md leading-relaxed text-slate-600">
              A rule inside the database blocks two bookings for the same doctor and time, even when two people tap at the same moment.
            </p>
            <div aria-hidden className="mt-7 grid max-w-md grid-cols-4 gap-2">
              {["09:00", "09:15", "09:30", "09:45", "10:00", "10:15", "10:30", "10:45"].map((t, i) => (
                <span key={t} className={i === 2 || i === 5 ? "rounded-lg bg-slate-100 py-2 text-center text-xs text-slate-400 line-through" : i === 3 ? "rounded-lg bg-teal-700 py-2 text-center text-xs font-semibold text-white" : "rounded-lg bg-mint py-2 text-center text-xs text-teal-900"}>{t}</span>
              ))}
            </div>
          </div>

          <div className="rounded-3xl bg-ink p-8 text-white shadow-lift md:col-span-2">
            <Radio aria-hidden className="h-7 w-7 text-ticket" />
            <h3 className="mt-5 font-display text-2xl font-semibold">A board that updates itself</h3>
            <p className="mt-3 leading-relaxed text-teal-50/85">
              Front desk and doctors see changes as they happen, with no refreshing.
            </p>
          </div>

          <div className="rounded-3xl bg-white p-8 shadow-lift ring-1 ring-ink/5 md:col-span-2">
            <Gauge aria-hidden className="h-7 w-7 text-teal-700" />
            <h3 className="mt-5 font-display text-2xl font-semibold text-ink">Estimates that show their source</h3>
            <p className="mt-3 leading-relaxed text-slate-600">
              Each one says whether it came from a trained model or a simple rule. It is a guide, never a promise.
            </p>
          </div>

          <div className="rounded-3xl bg-mint p-8 md:col-span-2">
            <ShieldCheck aria-hidden className="h-7 w-7 text-teal-800" />
            <h3 className="mt-5 font-display text-2xl font-semibold text-ink">Clinics kept apart</h3>
            <p className="mt-3 leading-relaxed text-teal-950/80">
              One clinic&apos;s records are separated from another&apos;s by rules in the database itself.
            </p>
          </div>

          <div className="rounded-3xl bg-white p-8 shadow-lift ring-1 ring-ink/5 md:col-span-2">
            <UsersRound aria-hidden className="h-7 w-7 text-teal-700" />
            <h3 className="mt-5 font-display text-2xl font-semibold text-ink">Each role sees its own view</h3>
            <p className="mt-3 leading-relaxed text-slate-600">
              Patients, front desk and doctors only get what they need. A doctor sees only their own queue.
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="how" className="border-y border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-5 py-24">
          <h2 id="how" className="font-display text-4xl font-semibold tracking-tight text-ink">How a visit works</h2>
          <ol className="mt-12 grid gap-10 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title}>
                <span className="tnum grid h-10 w-10 place-items-center rounded-full bg-ink font-display text-lg font-semibold text-ticket">{i + 1}</span>
                <h3 className="mt-5 font-display text-xl font-semibold text-ink">{s.title}</h3>
                <p className="mt-2 max-w-xs leading-relaxed text-slate-600">{s.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-24">
        <div className="relative overflow-hidden rounded-3xl bg-ink px-8 py-14 text-white md:px-14">
          <div aria-hidden className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-teal-600/30 blur-3xl" />
          <div className="relative md:flex md:items-end md:justify-between md:gap-10">
            <div className="max-w-xl">
              <h2 className="font-display text-4xl font-semibold tracking-tight">See it working.</h2>
              <p className="mt-4 leading-relaxed text-teal-50/85">
                Create a demo account, join a clinic and book a slot. Everything here is synthetic data.
              </p>
            </div>
            <Link href="/register" className="mt-8 inline-block shrink-0 rounded-xl bg-ticket px-7 py-3.5 font-semibold text-ink hover:brightness-95 md:mt-0">Create an account</Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-8 text-xs text-slate-500">
          <Logo />
          <p className="max-w-xl leading-relaxed">
            A portfolio demonstration with synthetic data. Not a medical record system; no regulatory compliance is claimed.
            Its wait-time model is trained on simulated data.
          </p>
        </div>
      </footer>
    </>
  );
}
