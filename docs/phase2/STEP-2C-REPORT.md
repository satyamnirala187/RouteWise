# Step 2C report: configuration and planning screens, end-to-end verification

**Date:** 18 October 2026; correction pass 19 October 2026 ([section 10](#10-correction-pass-19-october-2026)) · **Prepared by:** Claude Code · **Status: 2C implemented, including the correction pass; Phase 2 awaiting final review.** Phase 2 is **not** owner-approved or complete. 2C and its correction pass are one commit on top of `9c0db08`. The owner authorized a private GitHub repository for the history on 19 October 2026; nothing is deployed and nothing here claims deployment readiness. ₹0 spent; Notion not accessed. The phase summary is in [PHASE2-REPORT.md](PHASE2-REPORT.md).

**Base:** step 2B including its corrections, commit `9c0db089515e32f829bb74f45c815723b59e8580` (2A at `13de782`). 2C is committed on top of it. **Scope:** the admin configuration and planning screens, the rider destination card, and browser verification. No map view, navigation, calling, delivery status actions, rerouting, same-building grouping or offline work.

## 1. What was built

### Admin: Office, Warehouse and rider profiles (`Office & riders`)
- One card each for the **Office** and **Warehouse**: a label and coordinates as `latitude, longitude`. The card explains the format (decimal degrees inside DU North Campus, copied from a dropped pin) and says that moving a depot asks riders to confirm again.
  - Coordinates are checked in the browser first; the server stays authoritative and rejects anything outside the service area with its own message.
  - A "Check in Google Maps" link opens the saved point, the same pattern as Phase 1 order pins.
  - After a save, the card reports how many rider confirmations the move invalidated.
- **Rider profiles:** display name and default vehicle, with version checks. The screen says accounts are created and deactivated with the CLI; there is no account creation in the UI.
- There is no Maps-link resolver for depots or destinations: coordinates only, as the step allows. No second link resolver was created.

### Admin: Round setup (`Round setup`)
- For the selected round, each participating rider has vehicle (scooter / motorbike), capacity (whole orders, 1–1000), start (Office / Warehouse), Save and Remove.
- Each rider shows their **destination kind** and **confirmation state** (Confirmed / Not confirmed / Outdated — must confirm again) and lists what still blocks them, using the server's reasons.
- Home and Custom appear as "Home (private)" and "Custom (private)". The admin never receives those coordinates (the API never sends them), and the page says so.
- Riders can be added (defaults from the profile) and removed, and removed riders can be added back.
- There is no control that chooses or confirms a destination for a rider.

### Rider: destination card (existing rider page)
- **My rounds** lists only the rounds the signed-in rider takes part in, one card each (the API already scopes this; other riders' rounds are a 404).
- The summary shows start (with label), vehicle, capacity and destination. The rider's **own** Home/Custom coordinates appear only on their card, labelled "only you can see this".
- Five choices: Office, Warehouse, Home, Last stop (open route) and Custom. Home and Custom take coordinates, with format guidance.
- **Saving is not confirming.** After saving, the card says "Saved, not confirmed yet". Confirm is a separate button, enabled only when the saved setup has no open issues and there are no unsaved edits.
- States: Confirmed, Not confirmed, and Outdated ("Your setup changed after you confirmed it … confirm again").
- **Stale versions:** if the setup changed after the rider loaded it (`409 configuration_changed`), the card reloads the current version and asks the rider to review and confirm again.
- Confirmed rounds collapse to their summary with a "Change destination" button, so a rider in several rounds isn't faced with a stack of forms.
- The Phase 1 "My deliveries" list is unchanged. No navigation, calling or status actions.

### Admin: Orders (existing page, extended)
- Each order shows **Assigned: <rider>** (the owner from the current plan) separately from **🔒 Locked to <rider>** (the admin's owner lock) and **First delivery**. A lock is never shown as an assignment; a targeted defect check covers this.
- The order editor has a **Planning** section: an owner-lock selector (participating riders, or none), a first-delivery checkbox (Pending orders only, as the API enforces) and the current assigned rider.
- **Bulk owner assignment (for manual mode):** select Pending orders (or "Select unlocked Pending") and lock them to one rider, or clear their locks, in one all-or-nothing step. If any order changed meanwhile, the screen says nothing was saved, lists the order codes and offers a reload.

### Admin: Plan (`Plan`)
- **Distribution mode:** Smart, Equal or Manual, each with a one-line description. Equal says it is not guaranteed and that the plan will warn if the time-limited search misses it. Mode saves run one at a time per round (section 10).
- **Refresh readiness** button, and an automatic refresh when the admin returns to the tab or window: readiness, orders, plans and the latest run are reloaded for the selected round, with the time last checked shown (section 10).
- **Readiness checklist:**
  - order pins (listing the order codes that block);
  - Pending orders against the per-run limit;
  - participating and confirmed riders against the limit;
  - every rider-setup blocker in the server's words, naming the unconfirmed or outdated riders.
  - Each failing item links to the screen that fixes it.
- **Limits** are written out in plain language: up to 80 Pending orders, 8 riders and 100 distinct road points per run; each of up to three solver attempts stops after 30 s.
- **Optimize** is disabled with the reasons stated until the round is ready and no run is in progress. The server still decides; the button state is only guidance.
- **Run progress:** queued/running status with bounded polling (see section 2). The run continues on the server if the admin leaves.
- **Outcomes:**
  - **succeeded:** "plan version N saved".
  - **failed / stale / interrupted:** a red panel with the server's message, the order codes or riders it names, a how-to-fix line per code, and an explicit "The plan below is still version N from before this run; it was not replaced." The plan heading also says "Current plan (the latest run did not replace it)". An old plan is never presented as the new result; a targeted defect check covers this.
  - **Refused before scheduling** (e.g. `INSUFFICIENT_CAPACITY`, `PRIORITY_CONFLICT`, `MANUAL_ASSIGNMENT_MISSING`): "Planning was not started", with the same detail and fix, and "Nothing was saved".
- **Current plan:**
  - version, mode, Current/Superseded and saved time;
  - an **out-of-date banner** when the round changed afterwards;
  - totals in km, with riding time labelled "traffic-free estimate";
  - provenance: "**Recorded** real-road distances (replayed test data …)" or "**Live** road distances from local Valhalla (OpenStreetMap data)", plus the distance label, solver strategy and status, and the © OpenStreetMap attribution;
  - solver and equal-mode warnings exactly as saved;
  - **ownership changes** against the previous plan ("RW-… : Dev → Asha").
- **Each rider's route:**
  - vehicle and capacity, road distance and traffic-free time;
  - start (Office/Warehouse);
  - numbered stops with order code, customer and product;
  - the end: Office, Warehouse, Home (private), Custom (private), or "Last stop — the route ends at the final delivery (open route; no return leg counted)";
  - Postponed/Completed orders kept with the rider;
  - a rider with no Pending orders is labelled, with a note that the distance shown is their start-to-destination trip.
- **Version history:** each version with time, mode, order count, distance and Current/Out-of-date labels. "View" opens a past version under a "History: version N" heading with a Superseded badge, and "Back to the current plan" returns.
- **No map and no tile service.** Durations are labelled traffic-free everywhere; there is no ETA.

### Navigation and shared behaviour
- Main menu: **Orders · Round setup · Plan · Import · Office & riders**. The selected round lives in the URL (`?round=`) and carries across Orders, Round setup and Plan. Without it, the newest round is shown, as in Phase 1.
- Every page has loading, empty ("No rounds yet. Import an Excel file first."), error and 401 handling. A 401 anywhere returns to sign-in.
- Validation errors and version conflicts are shown next to the form that caused them. A conflict offers "Reload the latest version"; nothing silently overwrites newer configuration.

### Small API change
- `GET /api/admin/rounds/{id}/readiness` also returns `mode`, `pending_orders` and `planning_limits`. The fields are additive and read-only: the planning screen needs the round's mode and the configured limits, and no other endpoint exposed them. API test: `test_readiness_explains_mode_pending_count_and_limits`.
- No other API behaviour changed.

### Test-only browser seam
- `services/api/scripts/e2e_app.py` is the uvicorn factory used **only** by `playwright.config.ts`. It builds the normal app and injects the **recorded** real local-Valhalla DU matrices through the existing test-only `provider_override`; with `ROUTEWISE_E2E_LIVE=1` it uses the real local tiles.
- It also offers a hold file (`.local/e2e/hold-solve`) so a test can change input while a run is genuinely in progress.
- It lives outside the `routewise_api` package, is not selectable through configuration, and refuses to start in production.

## 2. Frontend quality

- **Reuse:** the Phase 1 shell, Tailwind tokens, API client (CSRF on every mutation, same-origin cookies, no cache) and component patterns.
- **Accessibility:**
  - every control is labelled (per-rider controls carry the rider's name, e.g. "Capacity for Asha");
  - radio groups use fieldsets and legends;
  - status and alert regions are announced;
  - checklist icons have screen-reader text;
  - touch targets are at least 44 px (`min-h-11`, nav links included);
  - all controls are native elements, so everything is keyboard-reachable.
- **Layouts at 390 px and 1280 px:** every 2C test asserts no horizontal page overflow on each screen it visits, at both widths. Wide tables stay inside their own scroll container, as in Phase 1.
- **Bounded polling** (`src/planning.ts`, `pollRun`):
  - the first poll waits 1 s, growing ×1.5 to at most 5 s, and gives up after 5 minutes with a "reload later" note;
  - it tolerates 3 consecutive network errors;
  - it stops at once on a terminal state, on abort (navigation, unmount, round switch) and on 401/403/404;
  - all of this is unit-tested with fake timers.
- **Stale responses:** every round-scoped request is aborted when the round changes, and a ref check drops any response that still arrives for a round no longer selected (for example a slow mode change). Since the correction pass, a load sequence number also drops any load that a newer load or a mode save has superseded. All paths are tested in the browser.
- **No browser storage:** no `localStorage`, `sessionStorage`, IndexedDB or cookie access in app code (grep-checked). The browser tests assert all three are empty for admin and rider pages after the flows.

## 3. Verification (18 October 2026, this Mac)

All browser planning evidence below uses **recorded** real-road DU matrices, except the separate live run.

| Check | Command | Result |
|---|---|---|
| Frontend type checks | `cd apps/web && npm run typecheck` | **OK** (app, specs and configs) |
| Frontend unit tests | `npx vitest run` | **13 passed** (5 Phase 1 + 8 new: polling stops on terminal state, abort, time budget, 401 and repeated network errors; structured errors; recorded/live and traffic-free labels) |
| Frontend build | `npm run build` | **OK** (338 kB JS, 101 kB gzip) |
| API suite | `cd services/api && .venv/bin/python -m pytest -q` | **321 passed, 1 skipped** (320 at 2B + 1 readiness contract test). The skip is the opt-in live API test, run separately |
| API live planning on local tiles | `ROUTEWISE_LIVE_TESTS=1 … -m live tests/test_planning_live.py` | **1 passed**; real_road, not recorded; total 22,848 m (as at 2B) |
| Spike regression (spike unchanged) | `cd spikes/routing && .venv/bin/python -m pytest -q` | **264 passed, 5 skipped** |
| Phase 0 local Valhalla checks | `ROUTEWISE_LIVE_TESTS=1 .venv-valhalla/bin/python -m pytest -q -m live tests/test_valhalla_du.py` | **2 passed** |
| **Browser suite, recorded matrices** (Phase 1 + Phase 2 specs, desktop 1280 px + mobile 390 px) | `E2E_SHOTS_DIR=<scratch> scripts/e2e.sh` | **24 passed, 2 skipped** (the skips are the opt-in live spec). Phase 1: 8 passed, unchanged. Phase 2: 16 passed (8 tests × 2 widths) |
| **Browser flow on real local Valhalla tiles** (opt-in, separate) | `ROUTEWISE_E2E_LIVE=1 E2E_SHOTS_DIR=<scratch> scripts/e2e.sh e2e/phase2-live.spec.ts` | **2 passed** (desktop and mobile). Provenance "Live road distances from local Valhalla (OpenStreetMap data)", `real_road=true`, `recorded=false`, profiles `motor_scooter` and `motorcycle`; 12 road points, matrices 0.09–0.16 s, solve 0.3 s; total 24,349 m; every order once |
| Targeted 2C defect checks (9; not exhaustive) | `python3 scripts/web_defect_check.py <scratch>` | **9/9 caught** (section 4) |
| Historical screenshots | SHA-256 of `docs/phase1/screenshots/*.png` and `docs/phase2/screenshots/*.png` before and after all runs | **20 files unchanged** |

Evidence: `docs/phase2/evidence/step2c_*.txt`. Screenshots: `docs/phase2/screenshots/2c/` (46 new files; nothing overwritten).

### What the browser tests cover (each at both widths)

| # | Test | Covers |
|---|---|---|
| 1 | Office/Warehouse and rider profile | Format and service-area validation messages; create or edit; another admin's newer edit refused with "changed since you opened it", then **Reload the latest version**; profile edit; CLI note |
| 2 | Full round | **Import through the UI** → add a mixed fleet (2 scooters, 1 motorbike) from **both starts** → Plan shows Optimize **disabled** with the riders named, and the **direct API call returns 409 `NOT_READY`** → riders choose **Home, Custom and Last stop** in their own sessions; saving is not confirming → with one rider still unconfirmed, Optimize stays disabled and that rider is named, and the API still refuses → after all confirm, a **smart plan**: every order exactly once, starts and ends as configured, Last stop as an open route, "Recorded real-road distances", OpenStreetMap attribution, traffic-free label → no Home/Custom coordinates in admin pages or admin API responses → no browser storage → Orders shows assigned riders |
| 3 | Modes, locks, priority | Owner lock and first delivery in the order editor (a lock is not shown as an assignment) → **equal** plan where the locked rider's first stop is the priority order → **manual** refused with `MANUAL_ASSIGNMENT_MISSING` and its fix, previous plan unchanged → **bulk owner assignment** → manual plan honours every lock → ownership changes reported → version history; viewing version 1 is labelled history/superseded. Office and Warehouse destinations are used here |
| 4 | Conflicts | `INSUFFICIENT_CAPACITY` and `PRIORITY_CONFLICT` explained with fixes; no run row and no plan created |
| 5 | Change during a solve | A run held in progress → the rider changes destination → **run rejected as stale**, plan 1 kept and labelled "did not replace it", out-of-date banner, only one version saved |
| 6 | Change after planning | Capacity change → rider Outdated, out-of-date banner, Optimize disabled with the reason; another admin's concurrent change refused with reload; the rider sees "Your setup changed after you confirmed it" |
| 7 | Isolation and privacy | A rider sees only their own rounds and cards and their own Home point, never another rider's Custom point. Server returns 404 for another round's setup or destination and for another rider's order, and 403 for admin endpoints and optimize. Admin pages and APIs carry no Home/Custom coordinates; storage empty |
| 8 | Polling, switching, expiry | A slow mode change for round A does not overwrite round B; polling stops on navigation and on round switch (0 requests in 3.5 s); delayed round-A responses never replace round B; **session revoked mid-poll → back to sign-in, 0 further polls** |

## 4. Targeted defect checks (new 2C risks only)

`scripts/web_defect_check.py` copies `apps/web` to a scratch directory, injects one defect, and runs only the browser test aimed at it (desktop). All 9 were caught:

| Injected defect | Caught by |
|---|---|
| Polling not stopped on navigation / round switch | test 8 |
| Poll errors ignored (session expiry keeps polling) | test 8 |
| Stale round responses accepted | test 8. This defect survived the first time: the original test only exercised requests that are aborted anyway. A slow, un-aborted mode change was added and it is now caught |
| Optimize enabled before readiness | test 2 |
| Plan not reloaded after a run ends | test 5 (this was a real bug found during development, see below) |
| Rejected run presented as the current result | test 5 |
| Saving a destination also confirms | test 2 |
| Version conflict silently reloaded over the admin's edit | test 6 |
| Owner lock shown as assignment | test 3 |

The 2B backend checks (13/13 at `9c0db08`) were not repeated: the backend changed only by the additive readiness fields, which have their own test.

## 5. Problems found and fixed during 2C

- **Plan not refreshed after a run finished.** A terminal run ends the polling effect, which aborted the reload it had just started. So a finished run neither showed the new plan nor the out-of-date banner. Fixed: the reload is not tied to the polling effect; it is guarded by the selected round instead. Found by the browser tests; kept as a targeted defect check.
- **Mode radio did not respond until the server replied.** Now the chosen mode shows at once while the save is pending (reworked in the correction pass: controls disabled until the server answers, then the server's mode is shown).
- **Duplicate fix text.** The stale-run panel repeated the server's "nothing was saved" in the fix line. Fix lines now add only the next step.
- **Rider page length.** A rider in many rounds saw every round's full form. Confirmed rounds now collapse to their summary.
- **Repeated depot label** ("Office — Office") removed.
- **Idle rider's distance** (a rider with no Pending orders still shows their start-to-destination trip) is now explained on the route card. Planning behaviour is unchanged from 2B (see limitations).
- **Test-only issues:** a race between a navigation click and the next page's round picker (tests now wait for the page heading); stop numbers matched as order codes (dedicated `stop-order` test id); round names repeat within a minute (rider cards carry `data-round`).

## 6. Screenshots (all synthetic data, inspected at both widths)

`docs/phase2/screenshots/2c/{desktop,mobile}-NN-*.png`:

| Screen | Files |
|---|---|
| Office & riders | `01-office-warehouse-riders` |
| Round setup | `02-round-setup-unconfirmed` (badges), `18-round-setup-outdated` (outdated + conflict reload) |
| Plan | `03-plan-blocked` (riders named, Optimize disabled), `06-plan-smart` (recorded, three ends incl. Last stop), `09-plan-equal`, `10-manual-refused`, `12-plan-manual` (ownership changes, history), `13-plan-history-version`, `14-capacity-conflict`, `15-priority-conflict`, `16-run-in-progress`, `17-run-stale`, `19-plan-out-of-date`, `22-round-switch` |
| Rider destination card | `04-rider-saved-not-confirmed`, `05-rider-confirmed`, `20-rider-outdated`, `21-rider-own-round` (card only) |
| Orders | `07-orders-assigned`, `08-order-lock-priority`, `11-bulk-assignment` |
| Live tiles | `live-plan` ("Live road distances from local Valhalla") |

The rider-card shots capture the card for the round under test. The synthetic riders join many rounds across the suite, so full rider pages are long and not useful as evidence.

## 7. How to run it (reproducible)

```bash
scripts/dev-db.sh start                                     # or: scripts/dev-db.sh init (first time)
cd services/api && .venv/bin/python -m pip install -r requirements.lock && .venv/bin/alembic upgrade head
../../spikes/valhalla/build_tiles.sh                        # once, if spikes/valhalla/data/valhalla_tiles is missing
.venv/bin/python -m routewise_api.cli create-user --username admin1 --role admin
.venv/bin/python -m routewise_api.cli create-user --username rider1 --role rider --name "Rider One" --vehicle scooter
.venv/bin/uvicorn --factory routewise_api.main:get_app --host 127.0.0.1 --port 8000
cd ../../apps/web && npm ci && npx vite                     # http://localhost:5173
```

Admin flow:
1. **Office & riders**: set the Office and Warehouse.
2. **Import** an .xlsx.
3. **Round setup**: add riders.
4. Each rider signs in and confirms a destination.
5. **Plan**: choose a mode and **Optimize routes**.

Tests: see `docs/DEVELOPMENT.md` (API, vitest, `scripts/e2e.sh`, the opt-in live browser flow and `scripts/web_defect_check.py`).

## 8. Limitations and open items

1. **Coordinates only** for Office, Warehouse, Home and Custom. There is no Maps-link entry for depots or destinations; Phase 1's link resolver is still used only for imported orders.
2. **No map view** (Q8). Plans are lists.
3. **Recorded vs live:** the full browser suite uses recorded real-road matrices for the 17 public DU points. Only one flow (both widths) ran on the live local tiles.
4. **Idle riders' distance:** a participating rider with no Pending orders still gets a start → destination route that counts toward the totals. This is unchanged 2B/spike behaviour, now explained on screen; whether idle riders should be left out is an owner decision.
5. **Equal mode** can miss the equal split at larger sizes (2B measurement). The screen states it is not guaranteed and shows the warning.
6. **Polling budget:** polling stops after 5 minutes (the run continues on the server); the admin presses **Refresh readiness** (or reloads) to see a late result.
7. **Rider page growth:** with no round archive, a rider's "My rounds" lists every round they take part in. Confirmed rounds are collapsed, but there is no archiving.
8. **Browsers:** tested in Playwright Chromium at 390 px and 1280 px only. No real phones, Safari or Firefox, no screen-reader pass, no CI.
9. **Readiness is not pushed live:** the Plan page refreshes on the button and on returning to the tab or window, not while the admin keeps looking at it. A rider's confirmation made while the admin stays on the page appears only after one of those. This is deliberate: no polling while idle.
10. **Mode changes across two admin tabs:** saves are serialized within one page. The mode endpoint has no version check (last write wins, as at 2B), so two admin tabs changing the same round's mode at once both succeed in turn; each tab then shows the server's mode after its own save or refresh. Any mode change also bumps the round's input version, so a plan run against the old mode is rejected as stale.
11. **Carried from 2B:** one API process per database; motorcycle costing is beta upstream; durations exclude traffic; no retention purge (D10); Q1, Q2, Q6, Q7 and Q8 remain pending owner decisions.

## 9. Changed files and Git state

**Git:** branch `main`. 2C, including the correction pass, is the commit after `9c0db08` (2B): "Add RouteWise planning screens and end-to-end verification". `apps/web/tsconfig.tsbuildinfo` is generated output and git-ignored (`*.tsbuildinfo`). Nothing is deployed.

**New:**
- Web pages and components: `apps/web/src/pages/{PlanPage,RoundSetupPage,SettingsPage}.tsx`, `apps/web/src/components/{PlanView,DestinationCard,ui}.tsx`
- Web helpers and tests: `apps/web/src/{planning.ts,planning.test.ts,useRounds.ts}`
- Browser specs: `apps/web/e2e/{phase2.spec.ts,phase2-live.spec.ts,phase2-helpers.ts}`
- Test harness: `services/api/scripts/e2e_app.py` (browser-test factory), `scripts/web_defect_check.py`
- Docs and evidence: `docs/phase2/STEP-2C-REPORT.md`, `docs/phase2/PHASE2-REPORT.md`, `docs/phase2/evidence/step2c_*.txt` (9 files), `docs/phase2/screenshots/2c/` (46 PNGs)

**Modified:**
- Web: `apps/web/src/{App.tsx,api.ts}`, `apps/web/src/components/{Shell,OrderEditor}.tsx`, `apps/web/src/pages/{OrdersPage,RiderPage}.tsx`, `apps/web/playwright.config.ts` (e2e factory)
- API: `services/api/routewise_api/routers/admin.py` (readiness fields), `services/api/tests/test_planning.py` (+1 test)
- Test harness: `services/api/scripts/e2e_setup.py` (four synthetic Phase 2 riders, public-point workbook), `scripts/e2e.sh` (hold-file reset, notes)
- Docs: `docs/DEVELOPMENT.md`, status lines in `README.md`, `CLAUDE.md`, `docs/README.md`, `docs/phase2/IMPLEMENTATION-PLAN.md`

Correction-pass files are listed in section 10.

**Not modified:** `docs/source/`, `spikes/`, `tests/fixtures/`, the routing core and planning service, Phase 0 / Phase 1 / 2A / 2B evidence, and every existing screenshot.

## 10. Correction pass (19 October 2026)

Focused on two Plan-page issues found in review. No backend, routing or API changes; nothing else on the page changed.

### 10.1 Readiness could stay stale while riders confirmed elsewhere

**Problem:** the Plan page loaded readiness only when a round was selected and after its own actions. A rider confirming in their own session left the admin looking at "not confirmed" with Optimize disabled until a full page reload.

**Fix (`apps/web/src/pages/PlanPage.tsx`):**
- A visible **Refresh readiness** button next to the round picker. It reloads readiness, orders, plan versions, the current plan and the latest run for the selected round; the round stays selected (it is in the URL and is not touched). A status line says "Checking…" and then "Readiness checked at HH:MM:SS".
- An automatic refresh when the window regains focus or the tab becomes visible again (`focus` and `visibilitychange` listeners, removed on round change and unmount). Nothing runs on a timer: the page does not poll while idle. A focus refresh is skipped if one is already running or a mode save is pending for that round.
- **Request guards:** a newer refresh aborts an older one; a round switch aborts it too; any load whose round is no longer selected is dropped; and a sequence number drops any load superseded by a newer one. A refreshed run never moves a run the page has already seen finish back to "running".
- If a refresh finds a run started elsewhere (for example in another tab), the existing bounded polling picks it up.

### 10.2 Mode changes could overlap

**Problem:** the mode radios applied a change optimistically and stayed enabled, so a second change could be sent while the first was still in flight, with the answers arriving in either order.

**Fix:**
- While a mode save is pending for the selected round: the three mode radios, **Optimize** and **Refresh readiness** are disabled. "Saving the distribution mode…" is shown, and the Optimize reason says "the distribution mode is being saved". The chosen mode is shown meanwhile, without changing the loaded readiness.
- After the server answers, success or failure, the page reloads the round's state from the server before re-enabling the controls, so what is shown is the saved mode. On success: "Mode set to X." On failure: "The mode was not changed: <server message>. The mode shown is the one saved on the server." (an alert); a 401 returns to sign-in as before.
- Pending saves are tracked **per round**. Switching to another round leaves that round's controls usable at once; switching back to a round whose save is still pending shows it as saving until it ends. A save that finishes after the admin switched rounds changes nothing on the round now shown and posts no message there. Loads already in flight when a save starts are dropped as superseded.

### 10.3 New browser tests (`apps/web/e2e/phase2.spec.ts`, both widths)

Slow requests are held by a test-controlled gate (`page.route`) and released by the test, so the order of events is fixed rather than timed.

| # | Test | Covers |
|---|---|---|
| 9 | Readiness refresh | Admin opens a round where Asha has not confirmed: Optimize disabled, Asha named. Asha confirms **in her own browser session**. For 3 s the admin page makes **no** readiness request and still shows the old state. **Refresh readiness** → blockers gone, "1 confirmed", Optimize enabled, same round selected. The rider then changes her destination through the API; a window **focus** event refreshes, and Optimize is disabled again with Asha named. A refresh for round A is held, the admin switches to round B, and the held response is released: B's readiness (2 riders) stays, Optimize enabled, B still selected. Browser storage empty |
| 10 | Serialized mode changes | (1) Held save on A: all radios, Optimize and Refresh disabled, saving status shown; a click on another radio sends nothing (exactly one PUT); after release "Mode set to equal.", controls re-enabled, server mode equal. (2) A save answered with a simulated 503: alert "The mode was not changed: Simulated server error.", Equal (the saved mode) checked, controls usable, server unchanged. (3) A held save on A, switch to B: B fully usable and its own mode change succeeds; back to A: still saving; release → "Mode set to manual.". (4) A's held save released while B is shown: B's mode, controls and messages unchanged; A shows the saved mode afterwards |

The simulated 503 is the only fabricated server response in the suite; it is labelled as simulated in the test and the screenshot.

### 10.4 Verification (19 October 2026)

| Check | Result | Evidence |
|---|---|---|
| Frontend type checks | **OK** | [step2c_correction_web_typecheck.txt](evidence/step2c_correction_web_typecheck.txt) |
| Frontend unit tests | **13 passed** (unchanged set) | [step2c_correction_web_vitest.txt](evidence/step2c_correction_web_vitest.txt) |
| Frontend build | **OK** (340 kB JS, 102 kB gzip) | [step2c_correction_web_build.txt](evidence/step2c_correction_web_build.txt) |
| Browser suite, recorded matrices (Phase 1 + 2, 1280 px + 390 px) | **28 passed, 2 skipped** (Phase 1: 8; Phase 2: 20 = 10 tests × 2 widths; the skips are the opt-in live spec) | [step2c_correction_e2e_playwright.txt](evidence/step2c_correction_e2e_playwright.txt) |
| Browser flow on real local Valhalla tiles (opt-in; rerun because it uses the changed Plan page) | **2 passed**; `real_road=true`, `recorded=false`, both profiles, 12 points, total 24,349 m (as before) | [step2c_correction_e2e_live_valhalla.txt](evidence/step2c_correction_e2e_live_valhalla.txt) |
| Targeted web defect checks | **15/15 caught**: the 9 earlier checks (the "stale round responses" one retargeted to the new guards) plus 6 new ones (section 10.5) | [step2c_correction_web_defect_checks.txt](evidence/step2c_correction_web_defect_checks.txt) |
| Existing screenshots | SHA-256 of all 66 PNGs under `docs/phase1/screenshots` and `docs/phase2/screenshots` before and after: **unchanged** | — |

**Not rerun**, because no backend or routing path changed: the API suite (321 passed, 1 skipped on 18 Oct), the live API planning test, the spike regression and the Phase 0 Valhalla checks. The 18 October evidence files are kept as they were.

### 10.5 Targeted defect checks added

| Injected defect | Caught by |
|---|---|
| No Refresh readiness action (button does nothing) | test 9 |
| No refresh when the window regains focus | test 9 |
| Readiness polled while idle (a 1 s timer) | test 9 (idle request count) |
| Overlapping mode saves allowed (radios stay enabled, no pending guard) | test 10 |
| Optimize enabled during a mode save | test 10 |
| Pending mode save shared across rounds | test 10 |
| Stale round responses accepted (retargeted: round and sequence guards removed) | tests 8 and 10 |

### 10.6 Screenshots

New, in a separate folder: `docs/phase2/screenshots/2c-correction/{desktop,mobile}-{23-readiness-refreshed,24-mode-saving,25-mode-save-failed}.png` (6 files, inspected at both widths). The 46 screenshots in `screenshots/2c/` are kept as they were taken on 18 October, so the Plan-page ones do not show the new Refresh readiness button.

### 10.7 Files changed in this pass

- `apps/web/src/pages/PlanPage.tsx`: refresh, focus refresh, request guards, per-round serialized mode saves.
- `apps/web/e2e/phase2.spec.ts`: tests 9 and 10 and a request-gate helper.
- `scripts/web_defect_check.py`: multi-place mutants; one retargeted, 6 added.
- Docs and evidence: this section and the edits above, `PHASE2-REPORT.md`, 6 `docs/phase2/evidence/step2c_correction_*.txt` files, 6 screenshots in `docs/phase2/screenshots/2c-correction/`.
