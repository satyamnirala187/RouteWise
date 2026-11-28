# Step 5A-1 report: the offline app shell

| | |
|---|---|
| Date | 28 October 2026 |
| Prepared by | Claude Code |
| Branch | `feature/phase5a1-offline-shell`, created from `docs/phase5-implementation-plan` at `122e913` (the Phase 5 plan), which sits on `main` at `4609df5` |
| Authorization | The owner authorized **5A-1 only**, on 28 Oct 2026. 5A-2 and later steps are **not** authorized ([plan](IMPLEMENTATION-PLAN.md)) |
| Status | Implemented, committed, draft PR open. **Awaiting owner review. Not merged.** |

## 1. What it does

A production build now registers a small service worker that caches **only the public app shell**: `index.html`, the content-hashed JS and CSS, the manifest and the icons. After one successful online visit, reloading the app, opening a deep link, or starting it with the server unreachable shows RouteWise instead of Chrome's offline page. **Deliveries are not available offline**: with no connection the app says "Connect to load your deliveries" and that nothing is saved on this device. Saving the rider's own list is step 5A-2.

Not done, as instructed: no rider snapshot, no IndexedDB, no queue, no migration, no new runtime dependency (`package.json` and the lockfile are unchanged), no change to the rider Route card, no deployment, no Notion, `routewise_phone` not touched, nothing merged.

## 2. The six requirements, and how each is met

| # | Requirement | How |
|---|---|---|
| 1 | Register only for a built app in a secure context; dev server unchanged | `src/offline/shell.ts`: needs `import.meta.env.PROD`, `isSecureContext` and `serviceWorker`. The build plugin has `apply: "build"`. The Vite dev server registers nothing (browser-tested on both projects) |
| 2 | Precache from real build output; intercept only same-origin navigations and listed files; never API, mutations, auth or customer data | `vite-plugin-shell.ts` reads the finished `dist`, hashes the files, and writes `sw.js` from `src/sw/worker.template.js` (`src/sw/generate.ts` holds the allowlist). The worker returns without `respondWith` for non-GET, cross-origin, `/api/…`, unlisted files, listed files with a query string, and file-like navigations |
| 3 | `sw.js` as JavaScript at the root; revalidation headers; immutable only for hashed assets; keep API `no-store` and all security headers | `main.py`: the SPA route sends `no-cache` and explicit types for `.js` and `.webmanifest`; `/assets/*` (200/304 only) is `public, max-age=31536000, immutable`; `/api/*` keeps `no-store`; every `SECURITY_HEADERS` entry including `geolocation=(self)` is asserted on every shell response |
| 4 | Tell a session-check network failure or timeout from a real 401; clear offline screen; no invented session; no logout | `loadSession` returns `null` **only** for a 401 and throws for anything else, with a 10 s bound. `App.tsx` shows `ConnectPage` ("Connect to load your deliveries", "You have not been signed out", "Try again", and a retry when the `online` event fires). Cookies are left alone |
| 5 | Update notice and next-launch behaviour without forced takeover; older tab keeps working; clean old caches safely | No `skipWaiting` on install. A waiting build shows "A new version of RouteWise is ready. It will be used the next time you open the app." with "Reload to update". It otherwise takes over when every tab is closed. An older tab is offered a reload when another tab applied the update and is never reloaded for it. Only `rw-shell-*` caches are removed, and only once the new build's own cache is complete |
| 6 | Do not claim deliveries are ready offline | No "ready" indicator exists; the connect screen says deliveries are not saved on this device. The indicator is proposed for 5A-2 |

Other behaviour: install **fails** (and deletes its half-filled cache) if any listed file is missing, not a 200, redirected, or of the wrong type, so the SPA fallback (HTML with 200) can never be cached as a missing icon or script. The cached `index.html` keeps the headers it came with, and the page honours them offline (tested, including `geolocation=(self)`).

## 3. First, the two questions asked

Evidence: [step5a1_spike_csp_offline.txt](evidence/step5a1_spike_csp_offline.txt) (a throwaway spec, deleted after the run).

- **CSP.** The current policy (`default-src 'self'`, no `worker-src`) **permits** a same-origin worker: registered at scope `/`, no `securitypolicyviolation`, no console errors. The final specs assert zero violations too.
- **Playwright offline emulation versus worker requests.** In Playwright 1.63.0 on Chromium, `context.setOffline(true)` **did** make the worker's own `fetch` fail (as it did for the page), and a stopped server did too. One probe, one browser. The specs still use a really stopped server for the core claims, as the plan said.

## 4. Verification (actual results)

Raw output is in [evidence/](evidence/). Everything ran against the isolated `routewise_test` / `routewise_e2e` databases and servers started by the tests. The phone server and `routewise_phone` were not touched, and **`apps/web/dist` was not rebuilt**: browser tests build to the git-ignored `apps/web/.e2e-dist`.

| Check | Result |
|---|---|
| Typecheck (`tsc` both projects) | clean |
| Vitest, all | **153 passed**, 11 files. New: worker and generator (40, the worker's own code run against a fake worker scope and cache), shell registration (15), app start-up states (8), session check (6 added) |
| Backend, affected | **58 passed** (`test_shell_headers.py` 16 new, plus the policy, privacy/SPA, auth, permissions and smoke tests). The phone-database tests were deliberately not run |
| `vite build` | succeeds; 6 public files precached; `npm audit --audit-level=high`: 0 vulnerabilities |
| FastAPI-served browser suite (`playwright.fastapi.config.ts`) | **9 passed**: the Phase 4 geolocation regression (still mocked geolocation) and the 8 offline-shell tests |
| Full Vite-served browser suite (`scripts/e2e.sh`, desktop + mobile) | **142 passed, 4 skipped** (the opt-in live specs), 6.8 min, includes the new dev-server spec |

**The 8 offline-shell tests** (Chromium, the built app served by FastAPI, a server the test starts and stops):
1. Installs under the current CSP; the cache is exactly the build's files (compared with the disk, by SHA-256); worker, HTML, manifest, icon and asset headers are right; no CSP violations.
2. **With the server stopped**, reload and deep links (`/`, `/login`, `/rider`, `/rider?round=…`, a round URL, `/admin/plan`, an unknown path) all show the app, served by the worker, not Chrome's offline page; the cached document still carries `geolocation=(self)` and the CSP.
3. First-ever offline access cannot work (a fresh browser gets `ERR_CONNECTION_REFUSED`); documented limit.
4. An unreachable server at start-up is **not** a sign-out (the session cookie is unchanged, no login form, "Try again" restores the signed-in rider), while a real server 401 shows the login form.
5. With a signed-in rider's customer data on screen, **no API response or request ever came from the worker** (login and logout included), Cache Storage holds only shell files, none contains the customer name, the CSRF token value, the username or the password, and browser storage is empty.
6. A failed precache (an icon the server does not have) installs nothing, leaves no cache, and the app keeps working.
7. Two builds, an older tab open: the update waits next to the old build; the older tab still signs in and out through the API and is not reloaded; applying it in another tab reloads that tab onto build 2, removes build 1's cache and keeps an unrelated cache; the older tab is offered a reload; build 2 then loads with the server stopped.
8. Two builds, no tab left: the waiting build takes over (next launch).

**Do the tests catch the defects they guard?** Three mutations were checked and each was caught, then restored: treating a network failure as signed out (7 tests failed), letting the worker intercept an API navigation (1), and forcing `skipWaiting` on install (1). The browser tests also found a real bug in my update logic (a page claimed by the first install was treated as a first visit, so it was never offered the reload); it is fixed with a unit test.

**Stability.** Before the failure described next, the two-build tests passed 4 repeats each. After it: the older-tab test alone 12 times, 8 further full runs of the config, and 25 repeats of the whole offline-shell file (200 test executions, [summary](evidence/step5a1_e2e_fastapi_repeat25.txt)); then the recorded run above. That is 46 later runs of the older-tab test, all passing.

**One failure I could not explain.** The first full run of the FastAPI-served config had 8 passed and 1 failed: in the older-tab test, tab B stayed on build 1 for 5 seconds after "Reload to update" ([log kept](evidence/step5a1_e2e_fastapi_first_run_failure.txt)). I could not reproduce it in those later runs. The test now prints the worker states, caches and navigations if it recurs. That step waited the default 5 s while the other update steps wait 15 to 20 s, so I raised those post-click waits to 15 s. I do not know whether it was machine load or a rare race in the update path; **I have not shown it was only load.**

## 5. Limitations and what was not verified

- **Chromium only, no real device.** Nothing here was run on the owner's phone, Android Chrome, iPhone/Safari or Firefox. A phone check is the owner's to do and would be owner-reported. **Airplane mode does not cut an `adb reverse` tunnel**: stop the server or unplug USB after loading the page once. Over the Wi-Fi HTTP address the browser will not run a worker at all.
- **The second build in the update tests is derived, not a second Vite run:** the first build's JS is changed (new hashed name), `index.html` repointed, and `sw.js` regenerated by the real generator. It exercises the update path, not Vite's rebuild.
- **A cached shell keeps the headers it was installed with.** A server header change reaches installed phones only when a shell file changes (the geolocation incident was a header). Release rule in [DEVELOPMENT.md](../DEVELOPMENT.md); not automated.
- **Cache-first means the first load after a deploy shows the previous shell** until the new build is applied. The API must stay compatible with the previous build for a release (a plan rule, not enforced yet).
- **Any non-401 failure shows the connect screen**, including a 5xx or an unreadable answer; by design, since only a 401 is a confirmed sign-out. A rider with a working connection but a failing server sees "Connect to load your deliveries".
- **"Reload to update" reloads the page**, so unsaved text in an open form would be lost. It is user-initiated and nothing reloads by itself.
- **A manifest means Chrome may now offer "Install app" or "Add to Home screen"** for a built app on HTTPS or localhost. The icons are plain placeholders (a white ring on the brand colour); artwork is the owner's call (Q5-13).
- **A port that once served the built app keeps its worker.** Reusing the same `localhost:<port>` for something else needs the site data cleared ([DEVELOPMENT.md](../DEVELOPMENT.md)).
- **`npm run build` will replace `apps/web/dist`**, which the owner's phone server serves; after the next build, a phone on `http://localhost:8020` (USB) will install the worker.
- **CI does not run the Playwright suites** (they are local); CI will run the new vitest and backend tests and the build.
- A failed worker **registration** is silently ignored (the app works without the offline shell); there is no user-facing message for it.

## 6. Still open (not decided here)

Q5-1 to Q5-13 in the [plan](IMPLEMENTATION-PLAN.md). In particular, **keeping another account's outbox on a shared device (Q5-8) and extending retention through backups (Q5-6) remain unresolved proposals, not approved defaults**; nothing in 5A-1 depends on either. Also still open from earlier phases: Q4-6, the provisional 4B/4C defaults, Q1 to Q8 from Phase 2, and the unidentified, unreproduced backend failure at the 4D checkpoint. Production readiness and the later Phase 5 steps are pending.

## 7. Files

- **Build and worker:** `apps/web/vite-plugin-shell.ts`, `vite.config.ts`, `tsconfig.node.json`, `src/sw/worker.template.js`, `src/sw/generate.ts`, `public/manifest.webmanifest`, `public/icons/icon-{192,512}.png`, `index.html`.
- **App:** `src/offline/shell.ts`, `components/UpdateBanner.tsx`, `pages/ConnectPage.tsx`, `App.tsx`, `main.tsx`, `api.ts`.
- **Server:** `services/api/routewise_api/main.py` (cache headers, MIME types).
- **Tests:** `src/sw/{generate,worker}.test.ts`, `src/offline/shell.test.ts`, `src/App.test.tsx`, `src/api.test.ts`; `services/api/tests/test_shell_headers.py`; `apps/web/e2e/{fastapi-offline-shell,phase5a1-dev}.spec.ts`, `e2e/shell-server.ts`, `services/api/scripts/e2e_shell_app.py`, `playwright.fastapi.config.ts`.
- **Docs:** this report, [evidence/](evidence/), the [plan](IMPLEMENTATION-PLAN.md) (5A split into 5A-1 authorized and 5A-2 proposal), [DEVELOPMENT.md](../DEVELOPMENT.md), the index and status lines. Historical screenshots and evidence were regenerated by the browser runs and **reverted**; `docs/source/` is unchanged.
