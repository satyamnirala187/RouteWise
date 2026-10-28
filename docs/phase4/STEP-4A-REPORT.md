# Step 4A report: quick next-customer call

> **Update 28 October 2026:** the owner approved Phase 4 **for local development** ([acceptance record](OWNER-ACCEPTANCE-2026-10-28.md)). Step 4A is part of that approval. Not production readiness; the limitations, provisional decisions and open items below stay open, including the unidentified and unreproduced backend failure in the 4D report. The text below is kept as written before the approval.

**Status:** 4A is **implemented, verified with automated tests, committed and pushed (§5), and awaiting owner review**. Phase 4 is **incomplete**: 4B, 4C and 4D have not started.

| | |
|---|---|
| Date | 19 October 2026 |
| Prepared by | Claude Code |
| Baseline | `3fa1e40` (Phase 3 accepted for local development) |
| Plan | [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) §3 4A |
| Requirements | R15; task P4-01; acceptance case A17 |

**Authorization:** the owner authorized **4A only**. This is not approval of the plan's other proposals: Q4-1…Q4-7, the GPS thresholds and the grouping rule all remain pending.

**Not done:** nothing is deployed, and Notion was not accessed.

## 1. What the rider sees

A **Next customer** panel sits directly above the existing Route card. The Route summary and version card is unchanged, at the owner's request.

**The panel shows:**
- the saved stop number and a **Next** label;
- the customer name and product, and the order code;
- a large **Call ⟨name⟩** button, using the validated `telLink`;
- **Customer unavailable**;
- a line under the buttons: *"Calling only opens your phone's dialer; it does not record an answer or change this order. 'Customer unavailable' postpones this order only; you can return it to Pending later."*

**How "next" is chosen:**
- It is the first Pending order of the first saved stop in the **server-confirmed** delivery view, so it follows the current plan, as in 3A/3B.
- Postponed and Completed orders are never chosen.
- An order outside the saved sequence is **never** chosen.

**Out-of-date route:** the label reads **"Next in saved order"**, plus *"Your route is out of date: this is the next stop in the saved order, not a newly optimized route."*

**Calling:** a tap on Call opens the dialer only. No request is sent and nothing is recorded: no answer, availability or status.

**Customer unavailable:**
- It sends the existing 3B **Postpone** request for that order, through the page's single `StatusActions`, which the stop cards also use.
- The panel and the cards therefore share:
  - one save in flight (every status button waits);
  - the version check and conflict reload;
  - "already done" repeats;
  - the uncertain-result retry;
  - the session-expiry redirect.
- The panel moves on only when the server-confirmed view arrives.

**Edge cases:**

| Case | What the panel shows |
|---|---|
| Undialable or missing contact | "Calling unavailable: ⟨reason⟩"; Customer unavailable stays available |
| Save in progress | "Saving…", disabled; all status buttons are disabled |
| Uncertain network result | The same customer, the 3B message and **Retry: mark Postponed** inside the panel |
| Conflict | The page's "Nothing was overwritten" notice and a reload |
| No plan yet | "No route has been planned yet, so there is no next customer…" |
| Pending orders outside the saved route only | "None in your saved route: … so none is picked as next. Ask your admin to optimize the round again." |
| Only Postponed orders left | "No Pending customers left. N Postponed orders stay with you…" |
| Everything completed | "All your deliveries in this round are completed." |
| No deliveries in the round | No panel; the existing message shows |
| Round switch | The panel follows the selected round only (existing late-response protection) |
| Session expiry | A return to sign-in, with nothing changed |

**Not added:**
- no GPS, rerouting or recalculation;
- no endpoint recalculation or grouping;
- no new availability status;
- no offline storage;
- no inactive or "coming soon" buttons.

## 2. Changed files

| File | Change |
|---|---|
| `apps/web/src/next.ts` (new) | `nextDelivery(view)`: the pure selection rule and the empty states |
| `apps/web/src/next.test.ts` (new) | 6 unit tests |
| `apps/web/src/components/DeliveryView.tsx` | The `NextCustomer` panel above the Route card. The Route card, the stop cards and their controls are unchanged |
| `apps/web/e2e/phase4a.spec.ts` (new) | 6 browser tests × 2 widths |
| `apps/web/e2e/phase3-helpers.ts` | `shooter()` takes an optional phase folder (default `phase3`). Existing callers are unchanged |
| `scripts/web_defect_check.py` | 8 targeted 4A defects; the 4A spec added to its run |
| `docs/phase4/IMPLEMENTATION-PLAN.md` | Status; 4A authorized only; the 4A section matches what was built |
| `docs/phase4/STEP-4A-REPORT.md`, `docs/phase4/evidence/step4a_*`, `docs/phase4/screenshots/4a/` (16) | New |
| `CLAUDE.md`, `README.md`, `docs/README.md` | Status lines |

**Unchanged:**
- `RiderPage.tsx` (the panel receives the existing `actions`);
- `links.ts`;
- every backend, routing, migration and API file.

## 3. Verification (actual results, 19 Oct 2026, 14:44 IST)

| Check | Result | Evidence |
|---|---|---|
| Web typecheck | OK | `evidence/step4a_web_typecheck.txt` |
| Web unit tests | 23 passed (17 existing + 6 new) | `evidence/step4a_web_vitest.txt` |
| Web build | OK | `evidence/step4a_web_build.txt` |
| Browser suite | **62 passed, 2 skipped** (64 tests) | `evidence/step4a_e2e_playwright.txt` |
| Targeted 4A defect checks | **8/8 detected** | `evidence/step4a_web_defect_checks.txt` |

**Browser suite details:**
- It ran every spec that renders the rider page: Phase 1, 2, 3A, 3B and the new 4A.
- Recorded real-road matrices, at 1280 and 390 px.
- The 2 skips are the opt-in live-tile tests.

**Defect checks:**
- **Detected:** Call recording a status, the panel moving before the server confirms, Customer unavailable enabled during a save, a Postponed or Completed order picked, an unsequenced order picked, an out-of-date route shown as plain "Next", an uncertain save hidden from the panel, and an undialable contact dialled.
- **First run:** one mutant's target text was ambiguous and stopped the run. It was corrected, and the affected checks were rerun one at a time; the log says exactly which.

**Not rerun:** the API, routing regression and live-tile suites. No backend or routing path changed.

**The 4A browser tests check:**
- **Panel content:**
  - the panel shows Stop 1's customer with the exact `tel:` target and accessible name;
  - it is above the Route card, whose plan version, ends and distance still render.
- **Calling:** a Call tap, by mouse and by keyboard with the dialer suppressed by the test, sends **no** non-GET API request. Every order keeps its status and version.
- **Customer unavailable:**
  - it postpones only that order; every other order's status and version are unchanged;
  - while the request is held: "Saving…" with `aria-busy`, every status button disabled, a duplicate tap sending nothing (one request), and the panel unchanged;
  - after the server confirms, the panel shows Stop 2's customer (A17).
- **Return and complete:** returning the order to Pending makes it next again. Completing it moves next on. Completed is never next.
- **Failures and conflicts:**
  - a request that never arrives keeps the same customer, shows the retry in the panel, and the retry saves;
  - a saved-but-lost answer keeps the customer, and the retry reports "already Postponed; nothing changed" with the version unchanged;
  - an admin completing the next order first gives "Nothing was overwritten". That order is not next, and the panel shows "Next in saved order", because the admin edit made the route out of date.
- **Empty states:**
  - Pending orders outside the saved route: no customer, no Call, no button;
  - only Postponed orders;
  - all completed;
  - a never-planned round: no customer chosen.
- **Undialable contact:** no Call link and the stated reason; Customer unavailable is enabled.
- **Isolation:**
  - in a shared round, the panel never contains another rider's order codes;
  - a late answer for the previous round never replaces the selected round's panel;
  - an ended session returns to sign-in, changes nothing, and leaves no browser storage.
- **Layout:** no horizontal overflow at either width.

**Screenshots:**
- 16 new synthetic screenshots in `docs/phase4/screenshots/4a/` (8 states × desktop and mobile).
- Inspected at 390 px and 1280 px: next customer, saving, after unavailable, uncertain, conflict/stale, not in route, all completed, no dialable contact.
- **Findings:**
  - Text is readable, and the buttons are at least 44 px (Call 48 px).
  - In `*-01` the Call button shows a focus ring because the test focused it.
- Phase 1–3 screenshots were not written: their output went to a scratch directory.

## 4. Limitations

- **Placement:** the panel is directly above the Route card, as asked, but on a phone the rider's setup card (2C) is still above it, so the panel is not at the very top of the page.
- **Navigate and Mark delivered** are on the stop card, not in the panel.
- **No availability record:** RouteWise cannot know whether a call was answered, and records nothing about it. "Customer unavailable" is the rider's explicit choice, saved as Postponed.
- **Stops with several orders:** the panel names the first in the server's order and counts the rest. Such stops occur only after 4C. The rider view does not carry the first-delivery flag, so priority ordering within a stop is 4C work.
- **No real phone check of 4A yet:** the dialer behaviour itself was checked on the owner's phone in Phase 3 through the stop cards, using the same `telLink`.
- **Carried from Phase 3:**
  - no country code is added to contacts;
  - no live refresh;
  - no offline queue (Phase 5).

## 5. Git state

- **Commit:** "Add RouteWise quick next-customer availability call", on top of `3fa1e40`, pushed to `main` of the public repository. It contains:
  - the Phase 4 plan (with the status updates above);
  - this report and its evidence and screenshots;
  - `apps/web/src/next.ts`, `apps/web/src/next.test.ts`, `apps/web/e2e/phase4a.spec.ts`;
  - the edits to `DeliveryView.tsx`, `phase3-helpers.ts` and `web_defect_check.py`;
  - the status lines in `CLAUDE.md`, `README.md` and `docs/README.md`.
- **Not done:** nothing deployed. 4B has not been started.
