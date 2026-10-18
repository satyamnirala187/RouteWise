# Step 3B report: rider delivery-status updates

**Date:** 19 October 2026 · **Prepared by:** Claude Code · **Status: 3B implemented and verified locally; awaiting owner review.** Phase 3 is **not** complete or accepted: the real-phone Call/Google Maps checks (A15, the P3-04 gate) have not been performed. 3B is one commit on top of `2b52cbc`; nothing is deployed; ₹0 spent; Notion not accessed.

**Base:** step 3A, `2b52cbc8a7e2e73a0e740ab210da5cc99f0c9219` ([3A report](STEP-3A-REPORT.md)). **Scope:** R16 for riders (statuses exactly Pending / Postponed / Completed, persisted on the server), task P3-03, acceptance case A16. Not built: offline queues or synchronisation (Phase 5); quick next-customer call, rerouting, reinsertion and same-building grouping (Phase 4); availability checks; package/dispatch confirmation.

## 1. What riders can do

| From | To | Rider action | Notes |
|---|---|---|---|
| Pending | Completed | **Mark delivered** → **Yes, delivered** | Two taps: a rider cannot reopen Completed |
| Pending | Postponed | **Postpone** | The order stays with the rider, outside the route order |
| Postponed | Pending | **Return to Pending** | Explicit. Goes back to its saved stop only if the current plan had one for this rider (section 3) |
| Completed | anything | — | Refused (`422 transition_not_allowed`); an admin can still edit it |
| Postponed | Completed | — | Refused; return it to Pending first |

**On the card:**
- Each status button is labelled with its order code (for example "Postpone: RW-001407").
- While a save is in flight, every status button on the page is disabled and the active one reads "Saving…" (`aria-busy`). A second tap sends nothing.
- The order does not move, and no success message appears, until the server answers.
- After success, the server returns the refreshed delivery view and the page shows exactly that:
  - the order moves to its section, and the section counts and the round picker's "N to deliver" update;
  - the next Pending stop gets the **Next** badge, and the other orders keep their relative order and stop numbers;
  - "RW-… saved as Postponed." is announced.
- Completed cards have no Call, Navigate or status buttons.
- Nothing calls, navigates, reassigns, optimizes or reroutes automatically.

**Recovery:**

| Situation | What happens |
|---|---|
| Changed elsewhere (`409 order_changed`), moved to another rider (`409 order_reassigned`), not allowed (`422`), gone (`404`) | The server's message is shown ("Nothing was overwritten; the latest status is shown" / "no longer assigned to you, so nothing was changed") and the view is reloaded from the server |
| Session expired (`401`) | Back to sign-in; nothing changes |
| Network failure or 5xx | The card keeps its last confirmed status, says "Could not confirm the save; showing the last confirmed status. The change may or may not have reached the server…" (a lost answer does not prove the save failed), and offers **Retry: mark …**. The retry sends the same expected version; if the first request had in fact been saved, the server answers "already …; nothing changed" |
| Round switched (or page left) before the answer | The answer is ignored for the screen; the round now shown is untouched |

## 2. API

`POST /api/rider/orders/{order_id}/status`, body `{"status": "Completed" | "Postponed" | "Pending", "expected_version": <int>}` (`StrictInt`; any other status, spelling or type is a 422). It needs a rider session and the session CSRF token with an allowed Origin (the existing dependency for every mutation).

| Outcome | Response |
|---|---|
| Not the rider's order, or no such order | `404 Order not found`; the same body for both, and no data |
| A plan moved the order to another rider before this request could lock the round | `409 {"code": "order_reassigned"}`; no status or version disclosed |
| The order already has the requested status | `200 {"changed": false, ...}`; nothing written, no version or input bump |
| `expected_version` ≠ current version | `409 {"code": "order_changed", "current_status", "current_version"}` |
| Transition not permitted | `422 {"code": "transition_not_allowed", "current_status"}` |
| Success | `200 {"changed": true, "order": {...}, "view": {...}}`. The order's status changes, `version` + 1 and `updated_at` is set, and the round's `input_version` + 1 (not `route_version`), in one transaction committed before the response |

**Repeats:**
- **Duplicate taps and retries** are harmless. A repeat finds the order already in the requested state and changes nothing.
- **Stale requests** never overwrite newer work. If the status differs, the expected version must match; that is how a stale request is refused rather than undoing a Completed order or an admin's edit.

**Read model changes** (additive):
- Delivery items carry the order `version`.
- Plans (rider view, admin plan, history) carry `progress_since_plan`.
- The admin's current plan carries `unplanned_pending`.

The existing `out_of_date` field keeps its name; its rule is section 3.

## 3. Progress versus route validity (exact rules)

Two revisions per round. Migration `0004` adds `delivery_rounds.route_version` and `route_plans.route_version`.

| Change | `input_version` (planning-input revision) | `route_version` (saved-route usability) |
|---|---|---|
| Rider's own Pending → Completed / Postponed, Postponed → Pending (rider endpoint) | **+1** | unchanged |
| Admin status edit (unchanged 2B semantics) | +1 | **+1** |
| Pins, depots, destinations, confirmations, capacities, vehicles, starts, participation, locks, priority, mode, account deactivation | +1 | +1 |

**Stale solves.** A planning run still records `input_version` and the keyed fingerprint of the whole input, statuses included. At commit, under the round lock, both must be unchanged, so **every** status change, including a rider's, makes a solve that started earlier end `stale`. Fingerprints and stale-solve protection are unchanged.

**Saved-route usability:**
- A committed plan records the round's `route_version`, read under the round lock after the final check. A plan's `input_version` and fingerprint are never rewritten.
- The saved routes are **out of date** exactly when `plan.route_version ≠ round.route_version`: a change other than riders' own progress has happened since.
- **`progress_since_plan`** is true when the plan is not out of date but `input_version` has moved, meaning only riders' progress has happened since. The rider page says "The remaining stops keep their saved order"; the admin page says the remaining saved stops are still valid.

**Remaining sequence.** The remaining sequence is the current plan's active stops for that rider, minus orders that are no longer Pending. Relative order and stop numbers are the plan's; nothing is recalculated.

**Postponed → Pending:**
- **Saved position exists:** if the current plan has the order as an active stop for this rider, it returns to that stop number. This reuses the saved position; nothing is invented.
- **No saved position:** if the plan held it as Postponed, it is listed under "Pending, not in the saved route" with "They need planning". The admin's current plan lists it in `unplanned_pending`, with a prompt to optimize again.
- **Not built:** operational reinsertion and rerouting (Phase 4).

**History and totals.** Plan rows, routes, stop numbers and totals are immutable. Totals are labelled as planned: "Planned total road distance", "Planned total riding time", and on the rider page "Planned road distance for the whole saved route … This is the plan, not the distance left." No live remaining-distance estimate.

**Existing data.** The migration copies each round's and each plan's `input_version` into `route_version`, so every plan's out-of-date state is exactly what it was before.

## 4. Locking strategy

The rider endpoint uses the existing order-edit lock order (documented in `planning.py`):

1. **Ownership check without locks** (join on the assignment): anything not the rider's is a 404.
2. **Order row `FOR NO KEY UPDATE`**, re-read (`orders.order_lock_options`, the same lock admin order edits take). Two updates to one order, from riders, tabs or an admin edit, serialise here.
3. **Round row `FOR UPDATE`.** A plan commit holds this lock from its final check to its last write, so once the rider has it no commit is in progress.
4. **Ownership re-checked** (fresh read of the assignment). If a plan has just given the order to another rider, the result is `409 order_reassigned` and the transaction rolls back, so a former owner's update cannot slip through.
5. Idempotency, version and transition checks; write; `input_version` + 1.

**No new wait cycle:**
- **Plan commits:** they lock depots → round and touch order rows only through foreign keys (KEY SHARE, compatible with FOR NO KEY UPDATE).
- **Admin order edits:** order → round, the same order as the rider endpoint.
- **Configuration writes:** depots → round → round-rider.
- **Deactivation:** depots → rounds → user.

The rider endpoint never locks depots, round-rider or user rows, and the round is always its last lock.

**Outcomes:**
- **Rider update first:** the run is stale; previous plan and assignments untouched.
- **Plan commit first:** an order that moved is refused; an order that stayed is updated, and the new plan stays usable.

## 5. Verification (19 October 2026, this Mac)

| Check | Result | Evidence |
|---|---|---|
| API suite | **355 passed, 1 skipped** (332 at 3A + 23 new in `tests/test_rider_status.py`; the skip is the opt-in live test) | [step3b_api_pytest.txt](evidence/step3b_api_pytest.txt) |
| API planning run on the real local tiles (opt-in; the plan commit changed) | **1 passed** | [step3b_api_live_valhalla.txt](evidence/step3b_api_live_valhalla.txt) |
| Phase 0 routing regression (planning-validity code changed; routing core did not) | **264 passed, 5 skipped** | [step3b_phase0_regression.txt](evidence/step3b_phase0_regression.txt) |
| Frontend type checks / unit tests / build | **OK / 17 passed / OK** (356 kB JS, 106 kB gzip) | [typecheck](evidence/step3b_web_typecheck.txt), [vitest](evidence/step3b_web_vitest.txt), [build](evidence/step3b_web_build.txt) |
| Browser suite, recorded matrices, 1280 px + 390 px | **50 passed, 2 skipped** (Phase 1: 8; Phase 2: 20; 3A: 10; **3B: 12 = 6 tests × 2 widths**; the skips are the opt-in live Phase 2 spec) | [step3b_e2e_playwright.txt](evidence/step3b_e2e_playwright.txt) |
| Targeted backend defect checks (3B only) | **9/9 caught** | [step3b_api_defect_checks.txt](evidence/step3b_api_defect_checks.txt) |
| Targeted web defect checks (3B only) | **6/6 caught** | [step3b_web_defect_checks.txt](evidence/step3b_web_defect_checks.txt) |
| Earlier screenshots | SHA-256 of all 82 earlier PNGs before and after: **unchanged** | — |

**Not rerun:** the opt-in live browser flow (no routing-engine or planning-UI change it covers).

**Wording correction before commit:** the unconfirmed-save message no longer says "Not saved", because a lost answer does not prove the save failed. Affected checks were rerun and all passed:
- type check, 17 unit tests and the build;
- the 3B browser spec, 12 passed (the test now checks the new message in both failure cases and that "Not saved" is absent);
- the renamed defect check, caught.

Evidence: [step3b_wording_fix.txt](evidence/step3b_wording_fix.txt). The table above and the other evidence files were recorded before this change.

### API tests (`tests/test_rider_status.py`, real PostgreSQL, recorded matrices)
- **Transitions.** Postpone moves the order out, keeps the others' order and moves Next; Return restores its saved stop number; Completed is final (Pending and Postponed refused, 422); Postponed → Completed refused; ownership unchanged throughout.
- **Validation** (5 cases): unknown or lower-case status, missing or string version, null; nothing changes.
- **Ownership and CSRF:** another rider and a random id get the same 404 with no data; invalid id 422; admin 403; signed out 401; no CSRF token 403; foreign Origin 403; nothing changes.
- **Stale versions:** after an admin text edit the rider's old version gets 409 with the current version. After an admin completes the order, a stale "Postponed" cannot undo it.
- **Repeats:** two repeats return `changed: false` with no version or input bump.
- **Concurrency:** both races hold the order row and release the competing requests together.
  - two tabs of the same rider: exactly one winner, the other gets 409 with the winner's status, and the version is bumped once;
  - an admin edit against a rider update: exactly one winner.
- **Route validity:**
  - Completing and postponing bump `input_version` twice and `route_version` not at all.
  - Every rider's plan stays usable with `progress_since_plan`, and remaining sequences keep their order.
  - Admin plan and history agree; totals and version are unchanged, and the plan's recorded versions are not rewritten.
- **Genuine invalidation after progress** (7 cases): pin, admin status edit, destination, capacity, depot, mode and lock each still mark the plan out of date for admin and every rider.
- **Return without a saved position:** an order held as Postponed by the plan returns as unsequenced and in `unplanned_pending`, the plan stays usable, the owner is kept, and re-planning includes it.
- **In-flight solve:** a rider update while a run is paused after solving makes the run `stale` with `INPUTS_CHANGED`; the saved plan and assignments are unchanged and the plan stays usable.
- **Replan race:** a plan commit holding the round after its final check moves the order to Rider B. Rider A's update for it waits (verified blocked on a lock), then gets `409 order_reassigned`. The order stays Pending, owned by Rider B and in B's sequence, and is gone from A's list.
- **Logs:** no customer fields or private coordinates.

### Browser tests (`apps/web/e2e/phase3b.spec.ts`, both widths)

| # | Test | Covers |
|---|---|---|
| 1 | Postpone, return, complete | Postpone the next stop: success only after saving, Postponed section, sequence and counts update, Next moves, picker "N to deliver" updates, Call still offered. Mark delivered: the confirm panel ("You cannot undo this yourself") saves nothing until **Yes, delivered**. Completed card has no buttons or links. Return to Pending: back at Stop 1 as Next. Afterwards: no out-of-date warning; "remaining stops keep their saved order"; totals "the plan, not the distance left"; server statuses match; no external request; no browser storage. Admin Plan page: "Riders have updated deliveries…", no out-of-date banner, "Planned total road distance", history badge "Deliveries updated" |
| 2 | In flight | A held request: the button reads "Saving…" with `aria-busy`, and every status button is disabled. Forced second taps on the same and another order send nothing (one request seen). The order has not moved and no success shows until release |
| 3 | Conflict | The admin completed the order meanwhile; the rider's Postpone shows "Nothing was overwritten", the list reloads showing Completed without buttons, the server still says Completed, and the route is reported out of date (an admin status edit is a genuine change) |
| 4 | Unconfirmed save | (a) Request blocked: "Could not confirm the save; showing the last confirmed status" (and never "Not saved"), order still Pending on screen and server, **Retry** saves it. (b) The server saves but the answer is lost: the same message, then Retry reports "was already Postponed; nothing changed" and the version is not bumped again |
| 5 | Needs planning | Postponed, re-planned (version 2 holds it as Postponed), returned to Pending: shown under "Pending, not in the saved route" with "They need planning", not in the sequence; the admin plan lists it in `unplanned_pending` and is not out of date |
| 6 | Round switch and expiry | A held update for round A answers after the switch to round B: B's view, list and messages are untouched (A's change is saved on the server). Session revoked, then a tap: back to sign-in, nothing changed |

`e2e/phase3-helpers.ts` now holds the helpers shared with the 3A spec (moved, not changed). No earlier spec assertion was changed.

### Targeted defect checks (new 3B risks only)

| Injected defect | Caught by |
|---|---|
| Backend: rider can reopen Completed | transitions test |
| Backend: ownership not re-checked under the round lock | replan race test |
| Backend: round lock not taken before the re-check | replan race test |
| Backend: stale version accepted | stale-version and concurrency tests |
| Backend: repeated request applied twice | repeat test |
| Backend: order row not locked | concurrency tests |
| Backend: rider progress bumps `route_version` (invalidates every route) | progress test |
| Backend: admin status edits stop invalidating | genuine-invalidation test (`admin_status`) |
| Backend: out of date judged on `input_version` | progress test |
| Web: status buttons enabled during a save | browser test 2 |
| Web: success shown before the server confirms | browser test 2 |
| Web: unconfirmed save reported as saved | browser test 4 |
| Web: conflict not reloaded | browser test 3 |
| Web: late status answer applied to another round | browser test 6 |
| Web: delivered without the second tap | browser test 1 |

## 6. Screenshots (synthetic data; inspected at 390 px and 1280 px)

`docs/phase3/screenshots/3b/{desktop,mobile}-…png`, 16 files in a new folder (nothing earlier overwritten):

| File | Shows |
|---|---|
| `01-actions` | Status buttons on each card |
| `02-confirm-delivered` | The second-tap panel |
| `03-after-progress` | Sections after postpone, complete and return; "remaining stops keep their saved order" |
| `04-admin-progress` | Admin plan: progress note, planned totals, "Deliveries updated" in history |
| `05-saving` | In flight, all status buttons disabled |
| `06-conflict` | "Nothing was overwritten"; route out of date after the admin's edit |
| `07-network-failure` | "Could not confirm the save" with Retry |
| `08-needs-planning` | Returned order listed as needing planning |

**Inspection fix:** at 390 px each card stacked four full-width buttons. Call/Navigate and the status actions are now two per row on phones (still at least 44 px tall), with single buttons and "unavailable" messages spanning the row. The final run's screenshots show the fix.

## 7. Limitations and open items

1. **No real phones.** Call/Google Maps links are still verified only as URLs in Chromium (A15 / P3-04). Status buttons are tested in Chromium at 390/1280 px only; no Safari, Firefox or screen-reader pass.
2. **Repeats rely on state, not on idempotency keys.** A repeat is recognised because the order already has the requested status. If an admin changes the order in between, the retry is refused with 409 (never applied); it is not matched to the earlier attempt. A full offline queue with replay rules is Phase 5.
3. **No offline use:** a failed save is not queued; the rider retries while online.
4. **Postponed → Completed** needs a return to Pending first (as specified). Riders cannot undo Completed; an admin can.
5. **Return-to-Pending placement:** an order returned with a saved position goes back to that stop number, even if the rider has already passed later stops. It then shows as Next. Smarter reinsertion is Phase 4.
6. **The admin plan view still lists every planned stop** without per-stop delivery status. Statuses are on the Orders page.
7. **`out_of_date` stays round-wide** for genuine changes: any non-progress change marks every rider's route out of date. Riders' progress no longer does.
8. **No live updates:** riders and admins press Refresh (or the admin returns to the page) to see others' changes.
9. **Carried over:** no retention cleanup; one API process per database; local development only. Pending decisions Q1, Q2 and Q6–Q8 remain open. Q1 (an "all orders Pending" replanning restriction) is still not built: admins can re-plan after progress, which keeps Completed and Postponed orders with their rider.

## 8. Changed files and Git state

**Git:** branch `main`. 3B is the commit after `2b52cbc` (3A). Nothing is deployed.

**New:**
- `services/api/migrations/versions/0004_phase3b_route_version.py`
- `services/api/tests/test_rider_status.py`
- `apps/web/e2e/phase3b.spec.ts`, `apps/web/e2e/phase3-helpers.ts`
- `docs/phase3/STEP-3B-REPORT.md`, `docs/phase3/evidence/step3b_*.txt` (10 files), `docs/phase3/screenshots/3b/` (16 PNGs)

**Modified:**
- API:
  - `routewise_api/models.py`: `route_version` columns.
  - `routewise_api/riders.py`: `bump_round_input(..., route=True)`.
  - `routewise_api/planning.py`: records `route_version` at commit; `plan_validity`; documentation.
  - `routewise_api/orders.py`: the shared order lock options.
  - `routewise_api/routers/rider.py`: status endpoint; order `version`; validity.
  - `routewise_api/routers/admin_planning.py`: validity; `unplanned_pending`.
- API tests:
  - `tests/test_migrations_privacy.py`: head revision `0004`.
  - `tests/test_rider_deliveries.py`: item fields now include `version`.
- Web:
  - `src/pages/RiderPage.tsx`: status saving and recovery.
  - `src/components/DeliveryView.tsx`: actions, progress note, planned-total wording, phone layout.
  - `src/components/PlanView.tsx` and `src/pages/PlanPage.tsx`: progress note, unplanned list, planned totals, history badge.
  - `src/api.ts`: types.
- Web tests: `e2e/phase3.spec.ts` (imports the moved helpers).
- Tools: `services/api/tools/mutation_check.py` and `scripts/web_defect_check.py` (3B checks).
- Docs: `docs/DEVELOPMENT.md` (endpoint, revision rule); status lines in `CLAUDE.md`, `README.md` and `docs/README.md`.

**Not modified:** `docs/source/`, `spikes/`, `tests/fixtures/`, the routing core, the planning run and fingerprint logic, every earlier report body, evidence file and screenshot.
