# Security follow-up: dependency-audit failures (22 October 2026)

**Status:** fixed in a separate maintenance commit (see `git log`; a document cannot contain its own commit hash). Two audit gates in CI failed on the Step 4D checkpoint `3838f98` because new advisories were published after the previous commit's CI run. The checkpoint itself changed no dependency. Real-phone testing and Phase 4 acceptance remain **pending**.

## 1. What failed, and why it was not the 4D change

CI run [39667187404](https://github.com/satyamnirala187/RouteWise/actions/runs/39667187404) for `3838f98`: only two **audit steps** failed. Every test and build step passed in that run (82 unit tests, build, 264 routing-spike tests, 454 API tests with 3 skipped), and CodeQL passed. `3838f98` changed no `package.json`, `package-lock.json` or `requirements.lock`, and the previous commit's CI (`8336ed0`) passed both audits. The advisories below were published on 20 and 21 October, after that run. The original logs are kept unchanged in [`evidence/ci-run-39667187404-failed-audit-steps.txt`](evidence/ci-run-39667187404-failed-audit-steps.txt).

| Gate | Finding | Severity |
|---|---|---|
| `npm audit --audit-level=high` (Web job) | `vite` 8.3.0 to 8.3.2 (the project pinned 8.3.1): [GHSA-587h-7wmj-h5pm](https://github.com/advisories/GHSA-587h-7wmj-h5pm) `launch-editor` `fs.existsSync()` check bypass on Windows | **high** (the one that trips the threshold) |
| same | [GHSA-698v-4r3x-3vcv](https://github.com/advisories/GHSA-698v-4r3x-3vcv) `launch-editor` `%` escaping on Windows; [GHSA-r825-w8mm-5pxw](https://github.com/advisories/GHSA-r825-w8mm-5pxw) `launch-editor` editor CLI flag misinterpretation; [GHSA-rq7h-c2jc-7f22](https://github.com/advisories/GHSA-rq7h-c2jc-7f22) files outside `server.fs.allow` served; [GHSA-vfpm-58rq-9qcg](https://github.com/advisories/GHSA-vfpm-58rq-9qcg) first 4 bytes of files outside `server.fs` via `?vite-wasm-instance` | medium |
| same | [GHSA-9jrq-w75r-8gcw](https://github.com/advisories/GHSA-9jrq-w75r-8gcw) cross-origin script execution through Vite custom middleware | low |
| `pip-audit` on `services/api/requirements.lock` (API job) | `certifi` 2026.7.22: [PYSEC-2026-4320](https://osv.dev/vulnerability/PYSEC-2026-4320) (alias GHSA-6q48-6c7w-9gw2), versions before 2026.10.18 bundle the `emSign ECC Root CA - G3` root whose intermediate CA keys were compromised | reported by `pip-audit` (its CI step does not rate severity) |

## 2. Verification of the patched versions (official sources)

Saved in [`evidence/advisory-and-registry-verification.txt`](evidence/advisory-and-registry-verification.txt).

- **Vite:** every advisory above lists `vite` >= 8.3.0, <= 8.3.2 as vulnerable and **8.3.3** as the first patched 8.3.x. The npm registry's `latest` is **8.3.5** (integrity `sha512-z1Ypjie…`), which is at or above every patched version and is the version npm itself proposed.
- **certifi:** OSV lists the affected range as ending at a fix in **2026.10.19**. PyPI has 2026.10.19 (a wheel and an sdist, neither yanked, `requires_python >=3.7`).

## 3. Exact changes

| File | Change |
|---|---|
| `apps/web/package.json` | `vite` `8.3.1` to `8.3.5` (still an exact pin) |
| `apps/web/package-lock.json` | `vite` 8.3.1 to 8.3.5 and the dependency resolution it requires: `rolldown` 1.2.13 to 1.2.15 with its 16 platform `@rolldown/binding-*` packages, `@oxc-project/types` 0.153.0 to 0.155.0, `postcss` 8.5.29 to 8.5.31. Nothing else moved |
| `services/api/requirements.lock` | `certifi` 2026.7.22 to 2026.10.19 |
| `spikes/routing/requirements.lock` | `certifi` 2026.7.22 to 2026.10.19 |
| `spikes/routing/requirements-valhalla.lock` | `certifi` 2026.7.22 to 2026.10.19 |

**Why the extra npm lines are required, not drift.** `vite@8.3.5` declares `postcss ^8.5.30` and `rolldown ~1.2.14`; `rolldown@1.2.15` declares `@oxc-project/types =0.155.0`. The locked versions before (8.5.29, 1.2.13, 0.153.0) did not satisfy them. No other dependency was touched, no source code changed, and the update was made with `npm install vite@8.3.5 --save-exact` (no `npm audit fix`, no `--force`). `certifi` was installed with `pip install certifi==2026.10.19` into the three local environments (`services/api/.venv`, `spikes/routing/.venv`, `spikes/routing/.venv-valhalla`); no database, credential or map tile was touched.

## 4. Validation (22 October 2026, all on the updated tree; outputs in `evidence/`)

| Check | Result | Evidence |
|---|---|---|
| `npm audit --audit-level=high` (the CI threshold), and `npm audit` with no threshold | **0 vulnerabilities**, exit 0 both | `audit-after-fix.txt` |
| `pip-audit` 2.10.1 (as CI runs it) on all three locks | **No known vulnerabilities found**, exit 0 each | `audit-after-fix.txt` |
| Web typecheck / unit tests / build (vite 8.3.5) | OK / **82 passed** / OK | `web-checks-after-fix.txt` |
| Browser suite, all phases, 1280 and 390 px (mocked geolocation) | **140 passed, 4 skipped, 0 failed** (the 4 skips are the opt-in live specs) | `browser-suite-after-fix.txt` |
| Backend suite, once, complete output captured | **454 passed, 3 skipped, 0 failed** | `backend-suite-after-fix.txt` |
| Routing regression (its environment changed) | **264 passed, 5 skipped, 0 failed** | `routing-regression-after-fix.txt` |

Long runs were made under `caffeinate -i` (a macOS built-in that only prevents sleep) so the Mac could not sleep mid-run, as happened in an earlier backend run (see the 4D report). Nothing was run more than once to reach a result, no advisory was suppressed, no threshold lowered, no audit disabled and no TLS verification bypassed. The CI result for the maintenance commit is shown on GitHub for that commit, not recorded here.

## 5. Notes and limits

- **Exposure, in my reading.** The Vite advisories concern its **development server** and the editor-opening helper (`launch-editor`); Vite is a dev dependency and the app is served from the built static files, so the practical exposure was to a developer's machine running `vite` (including the browser-test runs), not to a deployed app (nothing is deployed). `certifi` reaches the API through `httpx`; the app's own outbound HTTPS (short-link checks in `netsafe.py`) uses Python's default SSL context, not the certifi bundle, so I do not claim a direct exposure there. The audit gate is still correct to enforce.
- **Point in time.** The audits reflect the advisory databases on 22 October 2026. New advisories can appear at any time and fail CI again without any code change. Dependabot is configured weekly for `apps/web`, `services/api` and GitHub Actions, but **not** for the two routing-spike lockfiles, which pinned the same vulnerable `certifi`; whether to add them, or to batch or schedule such updates, is a decision for the owner. The previous commit's CI ran on 20 October 09:07 to 09:18 UTC, before the advisories were published (18:30 UTC onward).
- **Other findings** in the same audit runs: none (npm reported one vulnerable package, vite; `pip-audit` reported one, certifi).
- **Unchanged and pending:** the first full backend run's single unidentified failure from the 4D checkpoint is **not** related to this update and is still unidentified and unreproduced; Phase 4 acceptance and real-phone testing remain pending.
