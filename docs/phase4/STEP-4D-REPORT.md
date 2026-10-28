# Step 4D report: rider screens for individual rerouting and shared stops

> **Update 28 October 2026:** the owner approved Phase 4 **for local development** ([acceptance record](OWNER-ACCEPTANCE-2026-10-28.md)). Step 4D is part of that approval; the real-phone checks it listed were run by the owner and are recorded as owner-reported in [PHONE-TEST-RESULTS.md](PHONE-TEST-RESULTS.md), separate from the mocked-geolocation browser tests. Not production readiness; the limitations, provisional decisions and open items below stay open, including the unidentified and unreproduced backend failure in the 4D report. The text below is kept as written before the approval.

**Status:** 4D is **implemented, including its correction pass (section 8), and verified with automated tests (unit, browser at two widths with MOCKED geolocation, one opt-in browser run on the real local Valhalla tiles). It is committed as a checkpoint and awaiting owner review** (a report cannot contain its own commit hash; see `git log`). **Real-phone testing, including GPS, has not been done, and Phase 4 is not accepted.** Phase 4 stays **incomplete** until the owner runs the phone checks (section 6) and accepts it. **One open item:** the first full backend run had **1 failure whose test was not captured and has not been reproduced** (section 3); two complete reruns passed. Verification is therefore **not described as complete**. A review found two defects in the rider run handling; a correction pass fixed them (section 8, with its own results).

### Current verification summary (latest versus earlier)

The **latest** results are from the correction pass (22 October); the **earlier** ones are the first verification (20 October), made before the correction changed `useReroute.ts`, `reroute.ts` and `RerouteSection.tsx`. They are different runs and are not added together.

| Check | Latest (correction pass, 22 Oct) | Earlier (first verification, 20 Oct) |
|---|---|---|
| Typecheck / build | OK / OK | OK / OK |
| Unit tests | **82 passed** | 68 passed |
| Browser, 1280 + 390 px, mocked geolocation | **74 targeted runs passed, 0 failed:** `phase4d.spec.ts` (25 tests, 50 runs) plus `phase3b.spec.ts` and `phase4a.spec.ts` (24 runs) | **Full all-phases suite: 138 tests, 134 passed, 4 skipped, 0 failed.** Made before the correction pass and **not repeated after it**; only the rider-page specs were rerun |
| Browser on real local Valhalla (position mocked) | not rerun | 2 passed |
| Defect checks | 6 (all caught) | 16 (all caught) |
| Backend | no backend change; not rerun | first run **1 failed (unidentified, unreproduced)**, 453 passed, 3 skipped; two complete reruns **454 passed, 3 skipped** each |
| Screenshots | 14 added (46 in the folder; the 10 earlier-missing ones regenerated) | 32 |

Real-phone testing, including GPS, and Phase 4 acceptance are **pending**; Phase 4 is **incomplete**.

| | |
|---|---|
| Date | 20 October 2026 |
| Prepared by | Claude Code |
| Baseline | `8336ed0` (4C, with its review corrections) |
| Plan | [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) §3 4D |
| Requirements | R17 to R20, R22, R23; D05, D06, D08; tasks P4-02, P4-03, P4-04; acceptance cases A18 to A21 at browser level |

**Authorization:** the owner authorized **4D only**, and then its commit and push as a checkpoint. Nothing was deployed. Phase 5 was not started and Notion was not accessed. `routewise_phone` was not reset or upgraded (it is still on schema 0004; its credentials and data are untouched), no preview server was started, no tool was installed, no debugging was enabled and no device was connected. The only shared artefact rebuilt is the git-ignored `apps/web/dist`.

**No backend contract changed.** The screens use the 4B rider-reroute API and the 4C stop metadata exactly as they are. Backend changes are limited to a `localhost` mode in `scripts/phone-server.sh` and its tests.

## 1. What the rider sees

| Area | Behaviour |
|---|---|
| **Recalculate my route** | A section of its own between the next-customer panel and the Route card (the Route card is not inside it). Always offered on demand. Cues, never actions: after a **confirmed Postpone** ("Keep current order" or "Recalculate my route"; nothing happens unless the rider chooses), for **Pending orders outside the saved route**, and after a **changed destination is confirmed**. It re-orders only the rider's own remaining Pending orders through the existing rider-only API (own Pending orders only, ownership and held Postponed/Completed orders preserved, other riders untouched) |
| **Explicit origin** | Three buttons the rider taps; **none is preselected or remembered**. *Use my current location*; *From my last completed stop: RW-… (customer)*, offered only when the server offers it and labelled "Not your current position"; *From the Office/Warehouse (my configured start)*, offered only when the server permits it (they exclude each other) and labelled the same way |
| **Location** | Read **once**, only after the rider taps (`getCurrentPosition`, high accuracy, `maximumAge: 0`, 15 s; never `watchPosition`). Checked against the server's own `gps_limits` (100 m, 60 s) before anything is sent, and again by the server. Explained: denied, unavailable, timeout, too inaccurate, old, outside the service area, no road data. **Secure-context check:** on an insecure page, or without the API, the screen says "Location isn't available on this connection" and never asks; it never implies the Wi-Fi HTTP address can give GPS. No manual position entry, no tracking, nothing stored. The position is a local value between the read and the request: never in state, storage, URL, log or message |
| **Run safety** | Expected plan version and revision go with the request. One action at a time. Double taps send one request. A refresh **discovers the rider's own run** (`in_progress_run_id`) instead of starting another. Bounded polling (shared `pollRun`) stops on navigation, round change, sign-out and session expiry. **A lost answer is an unknown outcome:** the server state is read first; if it cannot be read only a read-only "check again" is offered, and the request is never sent again by itself. **Success is shown only after the server confirms the run and the effective delivery view shows the new revision.** Failed, stale (inputs changed, round replanned), busy and interrupted runs are worded differently and say "Your previous route is still shown." Status and setup actions wait while a run (or the wait for a position) is in progress, and a status save in flight holds the recalculation back. Offline, the action is disabled with an explanation (no cache, no queue) |
| **Shared stops** | Each saved stop is one container. A stop with several customers shows "N customers at this location" and **exactly one Navigate** (the server's validated stop location); every customer keeps their own name, product, notes, Call and status actions. Completing or postponing one leaves the others in the stop until none is Pending. The next-customer panel follows the server's order (a first-delivery customer leads a group). Ungrouped identical pins are never merged on screen. A one-customer stop keeps its Navigate in its card, so there is one per stop |
| **Route card** | Same layout; its data now reads the rider's **effective route**: revision number and origin, destination and distance. Totals are worded "Planned road distance for revision N of your route … the total planned for that revision when it was saved, not the distance left", with the traffic-free duration wording kept. After a destination change (also **new Home/Custom coordinates under the same kind**, detected through the server's `awaiting_recalculation`) it says the saved route still ends at the previous destination until a recalculation succeeds |
| **Admin plan page** | Per rider: "Recalculated by the rider at hh:mm from their ⟨origin kind⟩ (⟨order code⟩ for a last completed stop)", their current route's stops by order code, planned totals "not the distance left", the destination kind; the optimizer's saved plan follows, unchanged. Never a position or a private endpoint |
| **Phone preparation** | `scripts/phone-server.sh localhost` binds only to `127.0.0.1` and allows exactly `http://localhost:<port>` (for a USB test where the owner runs `adb reverse`). Wi-Fi mode and its safety settings are unchanged. `--print-config` prints the mode, host and origin and starts nothing. The script never runs `adb` |

## 2. Changed files

| File | Change |
|---|---|
| `apps/web/src/reroute.ts` (new) | One-shot position read, secure-context check, request bodies, refusal and run wording |
| `apps/web/src/useReroute.ts` (new) | The reroute state machine (lock, unknown outcomes, discovery, bounded polling, confirmation) |
| `apps/web/src/useOnline.ts` (new) | Online/offline state |
| `apps/web/src/components/RerouteSection.tsx` (new) | The "Recalculate my route" section |
| `apps/web/src/components/DeliveryView.tsx` | Stop containers, Route card data, blocked status actions, slot for the section |
| `apps/web/src/components/DestinationCard.tsx` | Setup actions wait during a run |
| `apps/web/src/components/PlanView.tsx` | Admin effective-route display |
| `apps/web/src/pages/RiderPage.tsx` | Wiring, the Postpone offer, a view reload that returns the view |
| `apps/web/src/planning.ts` | `pollRun` made generic so rider runs reuse the bounded polling |
| `apps/web/src/reroute.test.ts`, `useReroute.test.tsx`, `DeliveryView.test.tsx` (new) | 42 unit tests at first; 56 after the correction pass (14 more hook tests) |
| `apps/web/e2e/phase4d.spec.ts`, `phase4d-helpers.ts`, `phase4d-live.spec.ts` (new) | Browser tests (mocked geolocation) and the opt-in live run |
| `apps/web/e2e/phase4b.spec.ts`, `phase4c.spec.ts` | One assertion and one comment updated for the new admin note and the shared-stop container |
| `scripts/phone-server.sh`, `services/api/tests/test_phone_server_script.py` (new) | Localhost mode and its 11 tests |
| `docs/phase3/PHONE-TEST-GUIDE.md`, `docs/DEVELOPMENT.md`, `docs/phase4/IMPLEMENTATION-PLAN.md`, `docs/README.md`, `README.md`, `CLAUDE.md` | Status, the localhost-mode setup and the 4D checks |

CLAUDE.md previously said to keep the rider route summary card as it was; the owner's 4D request keeps its **design** and updates its **data**, and the file now says so.

## 3. Verification (actual results, 20 October 2026; the FIRST verification, before the correction pass)

*Sections 3 and 4 record the first verification. The correction pass of 22 October (section 8) changed the hook and the section component afterwards; its own, separate results and the current unit total (82) are in section 8.*

All browser positions are **mocked geolocation**: either emulated by the browser (Playwright `grantPermissions` + `setGeolocation`, which still goes through `navigator.geolocation` and the browser's permission) or a scripted stub for cases a browser cannot produce on demand. **No phone and no real GPS was involved.** Plans use the recorded real-road matrices unless stated.

### 3.1 Totals

| Check | Result | Evidence (`docs/phase4/evidence/`) |
|---|---|---|
| Web typecheck / unit tests / build | OK / **68 passed** in 7 files (26 before 4D; +18 `reroute.test.ts`, +15 `useReroute.test.tsx`, +9 `DeliveryView.test.tsx`) / OK. First verification; superseded by section 8 (82 tests) | `step4d_web_checks.txt` |
| Browser suite, **all phases**, 1280 + 390 px, recorded matrices, **mocked geolocation** | **138 tests: 134 passed, 4 skipped, 0 failed.** The 4 skips are the opt-in live specs (`phase2-live`, `phase4d-live`, two widths each). 44 of the runs are `phase4d.spec.ts` (22 tests x 2 widths). Earlier phases, 4A to 4C and the 4C review tests all still pass with the new rider screens | `step4d_e2e_playwright.txt` |
| Browser reroute on **real local Valhalla** (opt-in, `ROUTEWISE_E2E_LIVE=1`; position still **mocked geolocation**) | **2 passed** (desktop and mobile). `real_road: true`, `recorded: false`, origin `current_position`, 3 stops, 4,722 m, 520 s traffic-free, 0.83 s in the browser | `step4d_live_valhalla_browser.txt` |
| Backend, **first** full run | **1 failed, 453 passed, 3 skipped. Preserved unchanged.** The failing test's name was not captured and it has not been reproduced (section 3.2) | `step4d_api_pytest.txt` |
| Backend, complete rerun 1 | **454 passed, 3 skipped** | `step4d_api_pytest_rerun1.txt` |
| Backend, complete rerun 2 (under `caffeinate -i`, so the Mac could not sleep) | **454 passed, 3 skipped**, 280 s | `step4d_api_pytest_rerun2_caffeinate.txt` |
| Backend flake loops | `test_link_robustness.py` 15 times: 35 passed each. Concurrency, reroute, stop-group, rider-status and phone-server-script tests 6 times: 156 passed each | `step4d_api_failure_investigation.txt` |
| Defect checks (frontend, 16 defects) | Every one was caught by at least one test; two only by unit tests (section 4) | `step4d_defect_checks.txt` |
| Screenshots | **32 saved** in `docs/phase4/screenshots/4d/` (15 scenarios + the live run, two widths); **10 missing** (section 3.3) | `step4d_screenshots_note.txt` |

The backend suite is 454 tests (443 before 4D, plus 11 in `test_phone_server_script.py`: the script's `--print-config` modes, that it never runs `adb`, its safety settings, and that the app accepts exactly `http://localhost:8020` and nothing broader). **No other backend code changed.** The full browser run above was made on the tree as first implemented. After it, the defect-check edits were restored and compared byte for byte, and only unit-test and documentation files changed until the **correction pass (section 8) changed `useReroute.ts`, `reroute.ts` and `RerouteSection.tsx`. This full run was not repeated after that pass;** only the rider-page specs were (section 8.4).

**What the 22 browser tests cover** (each at 1280 and 390 px): a granted location recalculates only the rider's route from that position and says so (one read per tap, no `watchPosition`, nothing of the position left on the page or in storage, rider B and the admin's saved plan unchanged); every location problem (denied, unavailable, timeout, inaccurate, old) is explained, sends nothing and leaves the other starting points available; a browser-level denial falls back only when the rider chooses; a position outside the service area and one with no road data keep the previous route; an insecure page or a missing API says location is unavailable and never asks; offline disables the action; a double tap sends one request; a refresh follows the run already in progress; status and setup actions wait during a run, and a status save in flight holds the recalculation back; a lost answer is an unknown outcome (three variants: the run is found, nothing happened, the state cannot be read); a late answer for another round never changes the selected round; a run made stale by an admin edit is not saved; a busy planner, and interrupted, replanned and unroutable run answers, are worded separately; shared-stop container, one Navigate, per-customer cards and partial completion (A21); ungrouped identical pins stay separate stops; Postpone offers but never recalculates (A18), including the admin view and rider B unchanged; an order returned to Pending outside the saved route is offered and then placed; the last completed stop is offered and labelled; a destination change, including new Home coordinates under the same kind, shows the previous destination until confirm and recalculate, with only that rider affected and the admin page free of private coordinates (A20); another rider's run, round and route cannot be read or started; cancelling the location wait, signing out mid-run and an expired session stop everything.

**Mocked, not real, in these tests.** All positions (browser-emulated or scripted stub). The 503 "planner busy" answer and the "interrupted", "replanned" and "unroutable origin" run answers are **mocked server answers** (labelled in the test titles); the real recorded provider cannot produce them on demand. The stale case is real (an admin edit while the run is held). The "no road data" case is real but ends as `ROUTING_ENGINE_UNAVAILABLE`, because the recorded provider reports an unrecorded point that way.

### 3.2 The unexplained backend failure

The first complete backend run reported **1 failed, 453 passed, 3 skipped**. I filtered that run's output through `tail -12` and asked pytest for skips only, so **the failing test's name was not captured**, and I cannot recover it. The file is preserved as it was.

What is known (all in `step4d_api_failure_investigation.txt`): pytest measured 356 s while the process lived about 2 h 52 min of wall time. The macOS power log shows the Mac going to sleep at 20 Oct 16:08:33 and cycling through maintenance sleeps for hours. The test cluster's PostgreSQL log shows the suite's own deliberate constraint-violation errors stopping at 16:08:34 and resuming at 18:44:52, so the run was frozen for about 2 h 36 min inside the tests between `test_planning_concurrency.py` and `test_round_setup.py` (inferred from which files raise those errors). **Sleep during the run is a supported circumstance, not a proven root cause.** A hypothesis I did not verify: OR-Tools measures its solve time limit on the wall clock, so a multi-hour jump during a solve would end it at once without a plan.

It has **not been reproduced**: two complete reruns (454 passed each, one under `caffeinate`), 15 loops of the time-asserting module and 6 loops of the concurrency/reroute group all passed. **The failure is unidentified and unresolved, and nothing was weakened or changed in response.** I recommend watching the next CI run for this commit.

### 3.3 Missing evidence at the time of the first verification (HISTORICAL)

*This section describes the state when the first verification was written. The ten screenshots were regenerated by the correction pass (section 8.4); the other two items are still missing.*


- **10 screenshots, SINCE REGENERATED** (`01-choose-a-starting-point`, `02-recalculated-from-the-device-position`, `03-location-denied-with-fallback`, `08-recalculating`, `19-destination-changed-saved-route-ends-at-the-previous`, each at both widths). Their clean versions were overwritten, in the scratch folder, by the later defect-check runs, which re-ran those tests against deliberately broken code. The overwritten files are not used and are not in the repository. They were regenerated by the correction pass's run of `phase4d.spec.ts` and are now in the folder (46 files).
- **The live run's raw log (still missing)** was never written to a file. `step4d_live_valhalla_browser.txt` is copied from the terminal output (shown in the session), with that stated in its header; nothing was added.
- **The first backend run's failure details (still missing)** (section 3.2).


## 4. Defect checks

Sixteen defects were put back into the frontend source one at a time (a scratch edit, restored after each run and compared byte for byte afterwards), and the unit tests and the browser tests aimed at each were run (`step4d_defect_checks.txt`).

| # | Defect | Caught by |
|---|---|---|
| D1 | No one-at-a-time lock (a double tap sends twice) | **Unit tests only** (2). The browser double-tap test still passed: the screen hides the choices as soon as the first tap is handled, so a second tap cannot arrive. The lock is a safeguard that only the hook tests prove |
| D2 | Success claimed before the effective view shows it | Unit tests (4) |
| D3 | The request is sent again by itself after an unanswered one | Unit tests (6) and the browser lost-answer test |
| D4 | A Postpone recalculates automatically | Browser (after-Postpone test) |
| D5 | Status and setup actions do not wait during a run | Browser (waiting test) |
| D6 | The position is read when the choices open, before any tap | Browser (granted-location test) |
| D7 | The screen merges stops that share a pin | Unit tests (6) and the browser never-grouped test |
| D8 | A Navigate link on every customer of a shared stop | Unit tests (4) and the browser shared-stop test |
| D9 | A refresh does not discover the run in progress | Unit tests (2) and the browser refresh test |
| D10 | A late answer for another round is applied (no round epoch) | **Browser only** (late-answer test). The unit test still passed, probably because the cleanup also aborts the poll (not investigated further) |
| D11 | The device position is kept and shown | **Unit tests only** (2). The browser test passed: the kept text appears only in the choosing phase, which the browser test has left by the time it checks the page |
| D12 | New Home coordinates under the same kind go unnoticed | Unit tests (4) and the browser destination test |
| D13 | Rerouting is not disabled offline | Browser (offline test) |
| D14 | An unanswered request is treated as a refusal (nothing started) | Unit tests (6) and the browser lost-answer test |
| D15 | An inaccurate position is sent to the server | Unit tests (4) and the browser location-problem test |
| D16 | An insecure page is not recognised | Unit tests (4) and the browser insecure-page test |

**Gaps this showed.** D1 and D11 are covered only at unit level and D10 only at browser level; I did not add browser-level tests for D1 or D11 (D1 cannot be reached through the screen, and D11 would need a snapshot of the page while a position is being used). The defect checks cover the frontend only; the backend was not changed in 4D.

## 5. Limitations and what was not verified

1. **Real-phone testing has not been done.** Every GPS result above is **mocked geolocation**; the one real-routing check uses real local road data with a mocked position. How an Android phone, Chrome's permission prompt, real GPS accuracy and the `adb reverse` setup behave is unknown until the owner runs section 6. No phone server was started, no tool installed, no device connected. The localhost mode was verified only through `--print-config`, the script's text and the app's origin check, never by serving a page.
2. **Phase 4 is not accepted and is incomplete.** Q4-6 (the real-phone secure-context route) stays pending. The 4B limits (100 m, 60 s), "priority stays first", round-wide admin edits and refusing reroutes during an admin run, and the 4C grouping rule, remain provisional defaults.
3. **One backend failure is unexplained** (section 3.2), and the live run's raw log could not be recovered (section 3.3; the ten missing screenshots were regenerated). The **full** all-phases browser run (138 tests) predates the correction pass and was not repeated; only the rider-page specs (74 runs) were.
4. **A real GPS success needs the phone inside the DU North Campus service area** (the local tiles' coverage) and a secure page. Elsewhere the owner can only check the refusal and the fallbacks. Indoors, accuracy worse than 100 m is common, so the fallback path will often be the normal one.
5. **An admin optimizing during a rider's run** cannot be timed from the browser (the two commits cannot be ordered). It is covered at API level (4B); in the browser only the screen's wording for the stale and interrupted answers is checked, with mocked server answers.
6. **`progress_since_plan` is round-wide (3B behaviour, unchanged).** After any rider's delivery progress, every rider's Route card says "Deliveries have been updated since this plan was saved". It carries no other rider's data.
7. **Polling is bounded to about 90 s.** After that the rider sees "Still recalculating" with a read-only check; the server's own solve limit is 10 s. A finished-run message stays until dismissed or the next confirmed status change.
8. **`navigator.onLine` can say online without a working connection.** A failed request is still handled as an unknown outcome, never as success or as "nothing happened".
9. **One browser engine.** Tests run in Chromium at two widths; Safari and iPhone are untested, and the phone checks use one Android phone and Chrome.
10. **Origin rules come from the server.** A rider with a recorded completed stop is offered that stop (and the current position), never the configured start; the screen shows what the server allows and does not decide.
11. **The Route card changed its data at the owner's request** (design preserved). `CLAUDE.md` now says so; earlier reports' "unchanged" statements about it describe 4B and 4C.
12. **No offline cache or queue**, as specified.
13. **Run identity is partly inferred (correction pass, section 8).** The server's run view carries no plan version. A requested run is anchored to the plan version the server checked the request against; a run found by reading the server is anchored to the plan on the rider's screen at that moment, and is worded conservatively because its starter is not established. A certain match would need an additive backend field (the plan version on the run and the run id on the revision), which I did not add.

## 6. Owner phone-test checklist (short)

Full steps, the localhost-mode setup and the results format are in [PHONE-TEST-GUIDE.md](../phase3/PHONE-TEST-GUIDE.md) section E. **Real GPS can succeed only while the phone is inside the DU North Campus service area, and only in localhost mode (a secure page); on the Wi-Fi address location is correctly unavailable.** Record phone model, OS and browser only.

1. **Localhost mode:** you run `scripts/phone-server.sh localhost`, then `adb reverse tcp:8020 tcp:8020` with the phone on USB, and open `http://localhost:8020`. RouteWise runs nothing on the phone for you.
2. **Location granted:** tap Recalculate my route, then Use my current location. Expect the route recalculated "from your current position (device location)". Indoors the accuracy may exceed 100 m: record that message instead.
3. **Location denied:** the denied message, and nothing changes until you pick another starting point.
4. **Wi-Fi mode:** the location button is disabled with "Location isn't available on this connection"; the other starting points work.
5. **Last completed stop** (after delivering one) and **configured start** (before any delivery): each labelled "Not your current position".
6. **Postpone:** the page offers Keep current order or Recalculate; nothing recalculates by itself.
7. **Shared stop** (admin groups two orders and re-optimizes): one stop, one Navigate, each customer's own Call and status buttons; delivering one leaves the other.
8. **Destination change:** "still ends at the previous destination until you recalculate", then confirm and recalculate; another rider is unaffected.
9. **Offline** (airplane mode): the action is disabled with an explanation. **Touch and readability:** buttons easy to tap, no sideways scrolling.

## 7. Git state

- **Branch:** `main` at `8336ed0`, in sync with `origin/main` when 4D started.
- **Committed:** every file in section 2, the 4D evidence (`docs/phase4/evidence/step4d_*`, including the correction pass's `step4d_correction_*`), `docs/phase4/screenshots/4d/` and this report, as one commit on top of `8336ed0` ("Add RouteWise rider rerouting screens and shared stops") and pushed normally. The CI and CodeQL results for that commit are shown on GitHub for it, not recorded here.
- **Not done:** nothing deployed. Phase 5 was not started, Notion was not accessed, `routewise_phone` was not touched. Historical evidence and screenshots (earlier phases, 4A to 4C) and `docs/source/` are unchanged: the earlier screenshot folders were redirected to a scratch directory during every run.

## 8. Correction pass (22 October 2026): plan identity and unresolved state

A review found two defects in the rider run handling. The earlier implementation and evidence were kept; nothing in sections 1 to 7 was rewritten except where marked.

### 8.1 What was wrong

1. **A route was identified by its revision number alone.** `confirmSaved` and `checkState` compared revision numbers without the plan version. Revision numbers restart with every admin plan, so after an admin replan a revision of the *new* plan with the same number could be mistaken for the route that was requested ("Route recalculated…"), and a lost request could be reported as "nothing was recalculated, your saved route is unchanged" even though the admin plan had changed.
2. **Uncertainty lived in the message.** `RerouteSection` took its read-only safeguard from `rr.result.read`. **Dismiss** cleared that result, so the choices for a new recalculation reappeared while the server state was still unknown. A confirmed status change also dismissed the message.

### 8.2 What changed (frontend only; no backend change)

- **Plan version and revision are judged together** (`reroute.ts`: `Ctx`, `judgeSaved`, `judgeState`, `replacedText`). Each request or run carries a context: the plan version it was made against, the revision the rider was looking at, and whether this screen sent it ("requested") or found it by reading the server ("discovered"). The context is kept across read-only "Check again" actions, never re-derived from the screen as it is now.
- **If an admin plan superseded the requested route**, the screen says "Your admin replanned the round", names both plan versions, states that the requested route is **not** shown (or, for a lost request, that it cannot be told whether it reached the server), and shows the current plan's route. It never says the requested route is displayed, and never says the saved route is unchanged, merely because revision numbers match. The server state is then established, so actions return.
- **A later revision of the same plan** is reported as "A newer route is shown". After a lost answer, a changed route is described as made after the request but not matchable to it exactly.
- **Runs found by reading the server** (a page refresh, "already in progress" refusals, a run found after a lost answer) use conservative wording ("A recalculation of your route finished…"), because who started them and on which plan is not established. **The server's run view carries no plan version**, so a requested run is anchored to the plan version the server verified against (`ROUTE_CHANGED`), and a found run to the plan on the rider's screen when it was found. Making this certain would need an additive backend field; I did not change the backend.
- **What is unresolved is kept apart from the message** (`useReroute.ts`: `pending` and `unresolved`, kinds `unknown`, `confirm`, `run`). **`start()` and `open()` refuse while anything is unresolved**, in the hook as well as on the buttons. Dismiss clears only the message; `retire()`, used after a confirmed status change, never clears an unresolved message. `RerouteSection` shows "Your route is not confirmed" with **Check my route again** whenever something is unresolved, with or without a message, so the read-only check always stays reachable. Only a successful read that establishes the state, or a run reaching a known end, clears it, and the actions are restored then.

### 8.3 Regression tests added

| Scenario asked for | Test |
|---|---|
| A successful run, then an admin replan before its delivery view loads, with reused revision numbers | Hook: replan with revision 1 reused on plan 2, and plan 2 with no revision. Browser: the view read is held while the admin replans and the rider gets a revision 1 on plan 2 |
| A lost POST response, then a different admin plan | Hook: plan 2 with no revision, and with the same revision number. Browser: the state read is held while the admin replans |
| Dismissing an uncertain result while reads still fail: no second POST | Hook: dismiss, `start` (both origins), `open` and `checkAgain` with failing reads: one POST in total, choices not openable. Browser: dismiss, then a confirmed Postpone, then a failing check: the notice and the read-only check stay, the Postpone offer's button is disabled, no second POST |
| Resolving it through a successful read restores the actions | Hook: a successful read ends the uncertainty and a new request then works. Browser: the read succeeds, the choices button returns |
| Ordinary success and active-run recovery | The earlier tests are unchanged and pass: ordinary success, refresh discovering the run, REROUTE_IN_PROGRESS, the lost-answer variants |

Also covered: a newer revision on the same plan; a changed route after a lost answer; conservative wording for a found run, and for a found run whose plan was replaced; "Check again" keeping the request's own starting revision after the screen's view moved on (for example after a status change); a run that could not be followed stays unresolved until read; `retire()` keeps an unresolved message but retires an old success. **Two earlier browser tests changed expectation** (the refresh test and the lost-answer test that finds a run): they now expect the conservative "A recalculation of your route finished" wording instead of "Route recalculated…".

### 8.4 New verification (separate from section 3)

| Check | Result | Evidence |
|---|---|---|
| Web typecheck / unit tests / build | OK / **82 passed** (68 before; +14 hook tests) / OK | `step4d_correction_web_checks.txt` |
| Browser, 1280 and 390 px, mocked geolocation: `phase4d.spec.ts` (25 tests, 50 runs), `phase3b.spec.ts` and `phase4a.spec.ts` (the other rider-page specs, 24 runs) | **74 passed, 0 failed** | `step4d_correction_e2e_playwright.txt` |
| Targeted defect checks, 6 defects on the new behaviour | **All 6 caught.** E1 and E2 (the plan version ignored) by hook and browser tests; E3 (`start()` not refusing) and E6 (a status change retiring an unresolved message) by hook tests only; E4 (Dismiss clearing the uncertainty) by hook and browser tests; **E5 (the check re-deriving its context from the screen) was caught only by the browser test at first; I added a hook test and re-ran it, and now both catch it** | `step4d_correction_defect_checks.txt` |
| Screenshots | **14 added** (46 in the folder): the 10 that were missing, regenerated, and two new scenarios at both widths (`21-unresolved-after-dismiss`, `22-admin-replan-before-the-view-loaded`) | `step4d_screenshots_note.txt` |

**Not rerun**, because nothing they cover changed: the backend suite (no backend change; the unexplained failure below is unaffected), the full all-phases browser suite (only the rider-page specs were rerun), the live Valhalla spec, and the 16 earlier defect checks (the new six cover the changed code).

**Still open and unchanged by this pass.** The first full backend run's single failure remains **unidentified and unreproduced**; the two complete reruns passed. The Mac having slept during that run is a supported circumstance, **not** a proven cause. Real-phone testing and Phase 4 acceptance remain **pending**; Phase 4 is incomplete.
