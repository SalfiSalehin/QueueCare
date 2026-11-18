# Dependency audit (2026-11-18)

Run by hand on the development stack. **Backend:** `pip-audit -r backend/requirements.txt` found **no known vulnerabilities** (CI runs the
same check on every push). **Frontend:** `npm audit` reported 28 issues (9 moderate, 17 high, 2 critical) across all packages, but only
**3 in what is shipped to users** (`npm audit --omit=dev`). Triage below. This is a risk assessment by the author, not an external review.

## In the shipped app (3 findings): accepted for now, tracked
| Package | Severity | What it is | Why it is low risk here | Fix |
|---|---|---|---|---|
| `postcss` (a copy bundled inside `next`) | high | XSS via `</style>` in stringified CSS; reading `.map` files named by `sourceMappingURL` in a CSS comment | PostCSS only processes this project's own CSS at build time. No user-supplied CSS is ever parsed, in the browser or on the server. | Only by upgrading Next 15 to 16 (breaking). Planned as a deliberate migration. |
| `zod` 3.x | high | Memory exhaustion when validating very large constrained collections | Used in two places: the sign-in and register forms, validating what the person typed into their own browser. No server data or uploaded files are validated with it, and nothing there is a collection. | Zod 4 (breaking API change, needs a matching `@hookform/resolvers`). Planned. |
| (same `next` upgrade) | | Next 15.5.29 is also reported as outdated by its own dev server | | Next 16 migration, with the browser tests as the safety net. |

## Development and build tools only (25 findings): not shipped
These run on a developer's machine or in CI against this project's own files and never reach a user's browser or the production image.
* **`vitest` / `vite` / `esbuild` / `@vitest/mocker` / `tinypool`** (moderate, one flagged critical): the test runner and its helpers.
  The critical item is a prototype-pollution gadget in worker options; exploiting it needs an attacker to control how the test runner is
  configured, which they cannot. Fix is a vitest major upgrade, to be done on its own with the 46 unit tests as the check.
* **`tailwindcss` chain (`picomatch`, `micromatch`, `fast-glob`, `chokidar`, `readdirp`, `sucrase`)** (high): regex slowness when matching
  file patterns against this project's own source files at build time. Fix is Tailwind 4 (breaking).
* **ESLint chain (`@typescript-eslint/*`, `minimatch`, `eslint-config-next`)**: lint tooling. `npm audit fix` (no breaking changes) repairs the
  `minimatch` part.

## What is and is not done
* Done: backend scan clean; the lockfile is committed so installs are reproducible; CI re-scans the backend every push.
* Not done: the frontend upgrades above; `npm audit` is **not** a CI gate yet (it would fail today for the tooling findings). Revisit after the
  Next 16, Zod 4, Tailwind 4 and vitest upgrades.
* Not covered by this audit: the Docker base images (OS packages), a licence review, and a review of what npm packages do at install time.
