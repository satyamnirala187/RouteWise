# Phase 2 report: routing and multi-rider constraints

> **Update 19 October 2026:** the owner approved Phase 2 **for local development** at `41b37f8` ([record](OWNER-ACCEPTANCE-2026-10-19.md)). Not production readiness; the pending decisions and limitations below stay open. The text below is kept as written before the approval.

**Date:** 18 October 2026; 2C correction pass 19 October 2026 · **Prepared by:** Claude Code · **Status: all three steps implemented, including the 2C correction pass; Phase 2 awaiting the owner's final review.** It is **not** owner-approved or complete. Nothing is deployed (a private GitHub repository for the history was authorized by the owner on 19 October 2026); ₹0 spent; Notion not accessed (the tracker changes proposed in section 6 are for a human to apply after approval).

**Scope baseline:** [01-Product](../source/notion/RouteWise/01-Product.md) R07–R13 and R19 (R24 for privacy), [roadmap Phase 2](../source/notion/RouteWise/04-Roadmap.md), acceptance cases A12–A14, and [the Phase 2 plan](IMPLEMENTATION-PLAN.md). Delivery area: DU North Campus, Delhi. Routing: self-hosted local Valhalla only.

## 1. Steps and revisions

| Step | What | Revision | Report |
|---|---|---|---|
| 2A | Office/Warehouse, rider profiles, per-round rider setup, rider-chosen destinations, confirmation and version rules, readiness (API) | `13de782` | [STEP-2A-REPORT](STEP-2A-REPORT.md) |
| 2B | Local Valhalla + OR-Tools planning; modes, locks, priority; snapshots and keyed fingerprints; bounded worker; atomic versioned plans; stale rejection; recovery; account-deactivation correction (API) | `9c0db08` | [STEP-2B-REPORT](STEP-2B-REPORT.md) |
| 2C | Configuration and planning screens, rider destination card, browser verification (recorded and live); correction pass: readiness refresh and serialized mode changes | the commit after `9c0db08` | [STEP-2C-REPORT](STEP-2C-REPORT.md) (correction pass in §10) |

## 2. Acceptance checklist: requirement → evidence

Unless a row says otherwise, browser evidence is `apps/web/e2e/phase2.spec.ts`, run at 1280 px and 390 px on **recorded** real-road matrices ([step2c_e2e_playwright.txt](evidence/step2c_e2e_playwright.txt); after the correction pass [step2c_correction_e2e_playwright.txt](evidence/step2c_correction_e2e_playwright.txt)). API evidence is `services/api/tests/` ([step2c_api_pytest.txt](evidence/step2c_api_pytest.txt), 321 passed). Screenshots are in `screenshots/2c/`.

| Requirement | Evidence | Result |
|---|---|---|
| **R07** multiple riders, scooter/bike, capacities | Round setup UI (vehicle, capacity 1–1000) and API `test_round_setup.py`; mixed fleet planned with each rider's profile (`test_mixed_fleet_prices_each_rider_with_their_own_profile`; e2e test 2; live flow profiles `motor_scooter` + `motorcycle`) | Met |
| **R08** admin sets each start to Office or Warehouse | Round setup UI; e2e test 2 plans riders from both starts and shows "Start: Office / Warehouse"; screenshots `02`, `06` | Met |
| **R09** rider chooses Office/Warehouse/Home/Last stop/Custom | Rider destination card. All five are used across e2e tests 2, 3 and 5 (Home, Custom and Last stop in test 2; Office and Warehouse in test 3; a change to Warehouse in test 5). The admin cannot choose or confirm for a rider: no such endpoint or control (2A permission tests) | Met |
| **R10 / A12** optimization only after every participating rider confirms; blocked in **UI and API** | Optimize disabled with the unconfirmed riders named, and the direct API call returns `409 NOT_READY`, both checked in e2e test 2 (before any confirmation and with one rider left) and by API `test_unconfirmed_or_stale_confirmation_blocks_before_scheduling`; screenshot `03-plan-blocked` | Met |
| **R11** central optimization with real road distances | Local Valhalla only; a plan is saved only with `real_road=true` (API tests). **Live:** API run ([step2c_api_live_valhalla.txt](evidence/step2c_api_live_valhalla.txt)) and browser flow on the real tiles ([step2c_e2e_live_valhalla.txt](evidence/step2c_e2e_live_valhalla.txt), screenshot `live-plan`), both `recorded=false` | Met (local tiles; see limitations) |
| **R12** equal, smart and manual distribution | e2e test 2 (smart), test 3 (equal, then manual refused without owners, then bulk assignment and manual plan); API mode tests. Equal is labelled not guaranteed and its warning is shown | Met; equal can miss the band at larger sizes (2B measurement) |
| **R13** first-delivery priority | e2e test 3: the priority order is the locked rider's first stop; conflict explained in test 4; API priority tests | Met |
| **R19 / A13** every order exactly one owner; locks survive planning | e2e tests 2 and 3 assert every order appears exactly once and every lock is honoured; DB constraints and `test_database_enforces_one_current_plan_and_one_owner_per_plan`; ownership changes reported. Reroutes themselves are Phase 4 | Met for planning |
| **A14** a change during a solve cannot overwrite newer state | e2e test 5: a rider changes destination while a run is held in progress → run `stale`, plan 1 kept and labelled "did not replace it". API: 10 kinds of change during a solve, the commit-point race test and deactivation races (`test_planning_concurrency.py`, `test_account_deactivation.py`) | Met |
| Gate: fixed starts/ends and capacity | Route start and end labels checked in e2e test 2; `INSUFFICIENT_CAPACITY` explained in test 4; API capacity and held-capacity tests | Met |
| Gate: no silent omissions | Every Pending order planned exactly once or the run fails with a code (API `test_an_isolated_order_pin_fails_with_codes_and_nothing_is_dropped`; refusals shown in e2e tests 3–4) | Met |
| Gate: infeasibility handling | Coded refusals with fixes in the UI (`INSUFFICIENT_CAPACITY`, `PRIORITY_CONFLICT`, `MANUAL_ASSIGNMENT_MISSING` in e2e); the remaining codes are covered by API tests, with UI guidance for each in `src/planning.ts` | Met; only three codes exercised in the browser |
| Gate: real-road integration test succeeds | Live API test and live browser flow (above) | Met (opt-in, local tiles) |
| **R24** privacy of rider Home/Custom | Admin API responses carry kinds only (2A/2B tests). e2e tests 2, 6 and 7 assert no Home/Custom coordinate in admin page content or in any admin API response the pages use. A rider never sees another rider's points; browser storage is empty | Met |
| Plan out of date after configuration change | e2e test 6 (capacity change → banner, history "Out of date", rider Outdated); deactivation invalidation (2B correction) | Met |
| Version conflicts never silently overwrite | e2e test 1 (depot) and test 6 (round rider) show "changed since you opened it" and reload; rider `configuration_changed` handling; API 409 tests | Met |
| Polling bounded, cleaned up; stale responses ignored | e2e test 8 (navigation, round switch, session expiry; slow responses); unit tests for `pollRun` | Met |
| Readiness reflects riders' confirmations from other sessions | **Refresh readiness** button and refresh on window focus; no polling while idle. e2e test 9: a rider confirms in her own session, the admin page makes no request for 3 s, refresh enables Optimize; focus refresh shows a later change; a late refresh for round A never replaces round B | Met (correction pass) |
| Mode changes cannot overlap | Mode radios, Optimize and Refresh disabled while a save is pending, per round; the server's state reloaded afterwards; failure reported. e2e test 10 with held requests: one PUT only, simulated 503 recovery, other round usable, late answer for A changes nothing on B | Met (correction pass) |
| Mobile (390 px) and desktop (1280 px); keyboard; labelled controls | Every 2C test runs at both widths with an overflow assertion; native controls; screenshots inspected | Met in Chromium only |
| Targeted defect checks | 2B backend: 13/13 ([step2b_correction_targeted_defect_checks.txt](evidence/step2b_correction_targeted_defect_checks.txt)); 2C web: 9/9 ([step2c_web_defect_checks.txt](evidence/step2c_web_defect_checks.txt)), then 15/15 after the correction pass ([step2c_correction_web_defect_checks.txt](evidence/step2c_correction_web_defect_checks.txt)) | All caught |
| Regression | Phase 1 browser spec 8/8 (again on 19 Oct); spike 264 passed / 5 skipped; Phase 0 Valhalla checks 2/2; all earlier screenshots unchanged | Met |

## 3. Final verification runs

| Suite | 18 October 2026 | 19 October 2026 (after the 2C correction pass) |
|---|---|---|
| API (`pytest -q`) | 321 passed, 1 skipped (the opt-in live test) | not rerun: no backend change |
| API live planning on local tiles | 1 passed | not rerun: no routing change |
| Spike regression / Phase 0 Valhalla live | 264 passed, 5 skipped / 2 passed | not rerun: unchanged |
| Web typecheck / vitest / build | OK / 13 passed / OK | OK / 13 passed / OK |
| Browser, recorded matrices (Phase 1 + 2, both widths) | 24 passed, 2 skipped (live spec, opt-in) | **28 passed, 2 skipped** (2 new tests × 2 widths) |
| Browser, live local Valhalla (opt-in) | 2 passed | 2 passed (real roads, not recorded; 24,349 m) |
| Targeted defect checks (2C web) | 9/9 caught | **15/15 caught** |
| Earlier screenshots unchanged | 20 | 66 (new ones in `screenshots/2c-correction/`) |

## 4. Startup

See [STEP-2C-REPORT §7](STEP-2C-REPORT.md#7-how-to-run-it-reproducible) and [DEVELOPMENT.md](../DEVELOPMENT.md). In short: local PostgreSQL (`scripts/dev-db.sh`), `alembic upgrade head` (0001 → 0003), the Valhalla tiles built once with `spikes/valhalla/build_tiles.sh`, accounts made with the CLI, then the API on :8000 and Vite on :5173.

## 5. Limitations and pending decisions

**Limitations:**
- Local only, with one API process per database: no deployment, HTTPS, backups or CI.
- Tested in Chromium at 390/1280 px; no real phones, Safari, Firefox or screen-reader pass.
- Coordinates-only entry for depots and destinations; no map view.
- Durations exclude traffic; there is no ETA.
- The motorcycle costing is beta upstream.
- Equal mode can miss the equal split at larger sizes; the screen says so.
- An idle rider's start → destination trip is counted in totals; this is explained on screen.
- Snap legs are not costed, and no snap threshold is enforced.
- Re-planning may move unlocked Pending orders; moves are reported.
- No retention purge (D10).
- The browser suite uses recorded matrices; only one flow ran live.
- The Plan page refreshes readiness on the button and on returning to the window, not continuously; a confirmation made while the admin stays on the page appears after a refresh.
- Mode saves are serialized within a page; across two admin tabs the mode endpoint is last-write-wins (no version check, unchanged from 2B).

**Pending owner decisions (proposals, not approved):**
- **Q1** replanning restriction: not built.
- **Q2** destination change after issue.
- **Q6** size cap: 80/8/100 set locally from measurements; 100/8 remains a proposal.
- **Q7** snap threshold: 200 m is unverified.
- **Q8** map display.
- **B1:** real Office/Warehouse locations are entered by the owner and never committed.
- **New:** should riders with no orders be left out of a plan?

**Not built (later phases):** rider sequenced cards, navigation and calling (Phase 3); rerouting, endpoint-change reoptimization and same-building grouping (Phase 4); offline (Phase 5).

## 6. Proposed tracker updates (for a human to apply after approval; Notion not accessed)

- P2-01 … P2-05: "Implemented, awaiting owner review" with links to the three step reports.
- A12, A13, A14: "Passed locally (recorded matrices), 18 Oct 2026", plus the live local-tiles flow for real roads. Evidence links as in section 2.
- Open questions Q1, Q2, Q6, Q7 and Q8 unchanged; add the idle-rider question.

## 7. Git state

2A is `13de782`, 2B is `9c0db08`, and 2C (with its correction pass) is the commit after it, "Add RouteWise planning screens and end-to-end verification". Nothing is deployed. The changed files are listed in [STEP-2C-REPORT §9](STEP-2C-REPORT.md#9-changed-files-and-git-state).
