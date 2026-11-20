# Dependency audit

## Update, 2026-11-19: frontend upgrades done
After the first audit (below), the four framework upgrades it called for were made one at a time, each checked by the type-check, the unit
tests, the browser tests and a GitHub CI run before the next one started:

| Upgrade | From to | Checked by |
|---|---|---|
| Vitest (with an explicit `vite` dev dependency, config renamed `vitest.config.mts`) | 2.1.9 to 5.1.1 | 46 unit tests; CI run #6 green |
| Zod, with `@hookform/resolvers` | 3.x to 4.6.7, 3.x to 5.9.2 | 54 unit tests (8 new ones cover the sign-in and register rules); browser tests; CI run #7 green |
| Next.js (Turbopack is now the default bundler for dev and build) | 15.5.29 to 16.4.6 | 31 browser tests; CI run #8 green, including the production build |
| Tailwind CSS (`tailwind.config.ts` kept through `@config`; renamed `shadow-sm` to `shadow-xs`; v3 border colour and button cursor restored in `globals.css`) | 3.x to 4.x | 31 browser tests including 15 phone-width checks; CI run #9 green |

`npm install` after the last upgrade reported **0 vulnerabilities** (all packages, including development tools). The three findings in the
shipped app (the `postcss` copy inside Next, Zod 3, and the outdated Next) are gone with these upgrades.

Still true:
* `npm audit` is **not** a CI gate. It reports nothing today, so it could become one (a new advisory would then fail a push, which is the point
  but also means a build can break without a code change). Decide deliberately before turning it on.
* Not checked by a person: how the pages look after the Tailwind change. The tests catch overflow and broken flows, not a shadow that is now
  a little lighter. Compare the main screens by eye.
* Tailwind 4 needs Safari 16.4, Chrome 111 or Firefox 128 or newer; older browsers will not render the styles.
* The temporary `rollup` pin in `package.json` (`overrides`) is not yet reviewed: Vite 8 may not use rollup at all. Check `npm ls rollup`
  before removing it.

## First audit (2026-11-18, kept for the record)
Run by hand on the development stack. **Backend:** `pip-audit -r backend/requirements.txt` found **no known vulnerabilities** (CI runs the
same check on every push). **Frontend:** `npm audit` reported 28 issues (9 moderate, 17 high, 2 critical) across all packages, but only
**3 in what is shipped to users** (`npm audit --omit=dev`). This is a risk assessment by the author, not an external review.

* Shipped (3): a `postcss` copy bundled in `next` (XSS through `</style>` in stringified CSS; only this project's own CSS is processed, at build
  time), `zod` 3.x (memory exhaustion on very large collections; used only for two forms), and an outdated Next.
* Development and build tools only (25): `vitest`/`vite`/`esbuild` (one flagged critical: a prototype-pollution gadget needing control of the
  test runner's configuration), the `tailwindcss` file-matching chain (regex slowness on this project's own files), and the ESLint chain.
  These never reach a user's browser or the production image.

## Not covered by either audit
The Docker base images (OS packages), a licence review, and a review of what npm packages do at install time.
