# Phase 3 report: rider PWA screens

**Date:** 19 October 2026 · **Prepared by:** Claude Code · **Status: Phase 3 accepted for local development on 19 October 2026** ([owner acceptance record](OWNER-ACCEPTANCE-2026-10-19.md)). The acceptance rests on the automated evidence below and on owner-reported phone results. It is **not** production acceptance.

**Real-phone checks:**
- The owner ran them on a OnePlus Nord 5 with Chrome and reported the results: [results](PHONE-TEST-RESULTS.md), [guide](PHONE-TEST-GUIDE.md).
- These are **owner-reported device results**, not automated or independently observed checks.
- The functional checks passed on the original UI. The owner's feedback was that the delivery cards need clearer visual presentation.

**Card polish:**
- The cards were then polished (frontend only, §6).
- The owner reviewed the polished cards and confirmed they are clear and good (results V1, owner-reported).

Nothing is deployed; the source is public for review ([security review](../SECURITY-REVIEW.md)). ₹0 spent; Notion not accessed.

**Scope:**
- **Baseline:** [roadmap Phase 3](../source/notion/RouteWise/04-Roadmap.md) and the "Rider delivers" [working flow](../source/notion/RouteWise/02-Working-Flow.md).
- **Requirements and tasks:** R04, R06, R14, R16 and R24 (rider side); tasks P3-01…P3-04; acceptance cases A15 and A16.
- **Built on:** Phase 2, accepted for local development at `41b37f8` ([record](../phase2/OWNER-ACCEPTANCE-2026-10-19.md)).

## 1. Steps and commits

| Step | What | Commit | Report |
|---|---|---|---|
| 3A | Rider delivery view: own rounds and orders in the current plan's order, start/destination, Pending/Postponed/Completed sections, empty and out-of-date states; explicit Call (`tel:`) and Google Maps directions links from validated values; read-only rider APIs | `2b52cbc8a7e2e73a0e740ab210da5cc99f0c9219` | [STEP-3A-REPORT](STEP-3A-REPORT.md) |
| 3B | Rider status updates (Pending → Completed / Postponed, Postponed → Pending; Completed final for riders) with ownership re-checked under the round lock, version conflicts and safe repeats; `route_version` separates delivery progress from route invalidation | `e2139c1c7a69b893b800006e42be4b14c0e82fbe` | [STEP-3B-REPORT](STEP-3B-REPORT.md) |
| — | CI, Dependabot, `SECURITY.md`, security review before publication (no product change) | `8873bd7`, `bb9fb2d`, `20702aa`, `46b17ab` | [SECURITY-REVIEW](../SECURITY-REVIEW.md) |

## 2. Automated evidence (actual results)

| Suite | 3A (19 Oct) | 3B (19 Oct) | CI on `46b17ab` (GitHub Actions, Ubuntu) |
|---|---|---|---|
| API (`pytest`) | 332 passed, 1 skipped | 355 passed, 1 skipped | 355 passed, 1 skipped |
| Web typecheck / unit tests / build | OK / 17 / OK | OK / 17 / OK (wording fix rerun: OK / 17 / OK) | OK / 17 / OK |
| Browser suite, recorded matrices, 1280 + 390 px | 38 passed, 2 skipped | 50 passed, 2 skipped (wording fix: 3B spec 12 passed) | not in CI |
| Routing regression | not rerun | 264 passed, 5 skipped | 264 passed, 5 skipped |
| API planning on real local tiles (opt-in) | not rerun | 1 passed | not in CI (no tiles) |
| Targeted defect checks | backend 8/8, web 7/7 | backend 9/9, web 6/6 (+1/1 after the wording fix) | — |

**Notes:**
- **Skips:** in every row, the skips are opt-in live tests (local map tiles, or paid providers that are not configured).
- **Evidence files:** `evidence/step3a_*.txt` and `evidence/step3b_*.txt`.
- **Screenshots:** `screenshots/3a/` (10) and `screenshots/3b/` (16), synthetic data, inspected at 390 px and 1280 px. These show the original cards and are kept unchanged. The polished cards are in `screenshots/cards/` (§6).
- **Card polish (19 Oct, frontend only):**
  - typecheck OK, unit tests 17 passed, build OK;
  - full browser suite 50 passed, 2 skipped (`evidence/cards_polish_verification.txt`).
  - API, routing and live-tile suites were not rerun (no backend or behaviour change).

## 3. Acceptance criteria

The Phase 3 gate: *test a complete round on representative phones; links target the intended contact/location; status persists to the server; UI works with touch and keyboard; unauthorized cross-rider requests fail.*

| Criterion | Automated evidence | Real phone (owner-reported; #1–#14 on the original UI, V1 on the polished cards) |
|---|---|---|
| Own list and cards with product and instructions (P3-01, R04/R06) | API and browser tests at 390/1280 px (3A) | PASS, owner-reported (results #2); readability feedback led to the card polish; its visual check PASS, owner-reported (V1) |
| Call opens the dialer with the intended contact; nothing is called automatically (P3-02, R14, A15) | `tel:` link targets and refusals inspected in Chromium; no link followed | PASS, owner-reported: the dialer showed the expected number (#3). #4 was not reported |
| Navigate opens Google Maps at the intended location (P3-02, R14, A15) | Directions URL in the documented format, built from server-validated pins; inspected, not followed | PASS, owner-reported: all four links opened the correct destinations (#5–#6). Travel mode not supplied |
| Only Pending/Postponed/Completed; invalid values rejected (P3-03, R16, A16) | API: permitted transitions, invalid payloads and Completed reopening rejected | — |
| Status persists to the server (P3-03) | API and browser tests read the server state back; reload and sign-in tests | PASS, owner-reported (#7–#11) |
| Touch and keyboard (gate) | Labelled native controls; keyboard focus checked for Call; 44 px targets; no overflow at 390 px | Owner: "felt smooth"; cards need clearer presentation (#13: not reported as pass/fail). Keyboard was not tested on the phone |
| Unauthorized cross-rider requests fail (gate, R24) | 404 indistinguishable from missing for another rider's round or order; status updates re-check ownership; CSRF/Origin enforced | Optional Rider B check **NOT RUN / NOT REPORTED** (#12) |
| Complete round on representative phones (P3-04) | — | One phone (OnePlus Nord 5, Chrome), owner-reported, original UI. Not a full round: two of four stops were changed. Polished cards: visual check PASS, owner-reported (V1). Accepted by the owner for local development |

## 4. Open items

1. **Phone tests:**
   - **Results** ([results](PHONE-TEST-RESULTS.md)), all owner-reported:
     - the functional checks passed on the original UI;
     - the visual check of the polished cards (V1) passed.
   - **Accepted:** the owner accepted this evidence for local development ([record](OWNER-ACCEPTANCE-2026-10-19.md)).
   - **Left open, not inferred:**
     - the optional Rider B check (#12);
     - check #4;
     - unreported details: OS/browser versions, test time, commit tested, travel mode.
   - **Not tested:**
     - iPhone/Safari and other phones;
     - a full delivery round on a phone;
     - keyboard use on a phone.
2. **Limitations carried from 3A/3B:**
   - Google Maps chooses its own road and mode; two-wheeler availability is region-dependent.
   - No country code is added to contacts.
   - No offline queue (Phase 5); no quick next-customer call, reinsertion or rerouting (Phase 4).
   - "Out of date" stays round-wide for genuine changes.
   - The admin plan view has no per-stop status.
   - No live refresh.
3. **Still open:** the owner decisions Q1, Q2 and Q6–Q8 from Phase 2.

## 5. Phone-test tooling (local only)

**What the scripts do:**
- `services/api/scripts/phone_setup.py` resets only the isolated database `routewise_phone`. It creates one admin and two synthetic riders with random passwords, and imports 8 synthetic customers on public DU points through the real import. Riders confirm their destinations, and the round is planned on the local Valhalla tiles.
- It can store one owner-entered number, at a hidden prompt, as the contact of Rider A's first stop. That number stays only in that database.
- Passwords and expected stops go to the git-ignored, owner-only `.local/phone/`.
- `scripts/phone-server.sh` builds the web app and serves only the app (API plus pages, one origin) on the Mac's Wi-Fi address, port 8020, against `routewise_phone`. PostgreSQL stays on 127.0.0.1. There are no access logs; the address is printed only to the terminal.

**Dry run on this Mac (server bound to 127.0.0.1, not the network):**
- **Setup:** succeeded (plan on live local roads, `recorded=false`).
- **Server:** health and pages answered.
- **Rider A:** saw one round with 4 stops and a current plan.
- **Listeners:** the app and PostgreSQL were the only ones, both on 127.0.0.1.
- **Clean-up:** the server was stopped and the dry-run credential files were deleted.

No phone was used.

## 6. Delivery-card clarity polish (after the phone test)

**Why:** the owner's phone feedback was "delivery cards need clearer visual presentation".

**Where:** only the rider card in `apps/web/src/components/DeliveryView.tsx`. No new feature, library, animation or design system. Existing Tailwind tokens only.

**Changes:**
- **Hierarchy:** stop number and Next (larger, same row), then the customer name (larger, bold), then the product. The order code moved to a small "Order …" line under the product.
- **Status badge:**
  - The rider card has its own larger badge, with a coloured dot, a ring and a "Status:" prefix for screen readers.
  - Each card also has a coloured left edge per status. The badge text carries the meaning, so colour is never the only cue.
  - The admin `StatusPill` is unchanged.
- **Details:**
  - Delivery instructions and Contact are separate, labelled rows in an inset panel (`dl`/`dt`/`dd`).
  - Their text content is unchanged ("Delivery instructions: …", "Contact: …").
- **Actions:**
  - Call and Navigate sit under a labelled "Reach the customer" group.
  - A divider separates them from the labelled "Update delivery status" group.
  - The delivered confirmation and the retry message stay inside the status group.
  - The Postpone, Return to Pending, Navigate and Cancel outlines are darker (ring colours with higher contrast on white).
- **Cards:**
  - Wider gaps between cards (16 px instead of 12 px). The Next card keeps its blue outline.
  - Completed cards are compact (tighter padding, inline instructions and contact) and still have no buttons or links.
- **Touch:** targets stay at least 44 px.

**Preserved (checked by the browser suite):**
- link targets (`tel:` and Google Maps directions, `_blank` with `noopener noreferrer`);
- accessible names;
- the two-tap delivered confirmation;
- one save at a time;
- conflict and retry handling;
- ownership rules;
- no horizontal overflow at 390 px.

**Test change:** one screenshot call added to the 3B spec (`02b-all-statuses`: Pending, Postponed and Completed together). No assertion changed.

**Verification (19 Oct 2026, actual results):**
- typecheck OK, unit tests 17 passed, build OK;
- full browser suite (Phase 1, 2, 3A and 3B specs, 1280 and 390 px): 50 passed, 2 skipped (opt-in live);
- evidence: `evidence/cards_polish_verification.txt`.

**Screenshots:**
- New screenshots are in `screenshots/cards/3a/` (10) and `screenshots/cards/3b/` (18).
- The earlier `screenshots/3a/` and `3b/` are unchanged.
- Inspected at 390 px and 1280 px, mainly `cards/3b/*-02b-all-statuses.png` (all three statuses), `cards/3b/*-02-confirm-delivered.png` and `cards/3a/mobile-01-route.png` (instructions, plus a contact that cannot be dialled).

**Status:**
- The original UI passed the owner's functional phone checks.
- The polished cards were checked in desktop Chromium at 390 px and 1280 px.
- The owner then reviewed them and confirmed they are clear and good (results V1, owner-reported).
- The route-plan summary and version card was not changed and stays as it is at the owner's request.

## 7. Git state

**Commit:** "Finalize RouteWise Phase 3 phone validation and delivery cards", on top of `46b17ab`, pushed to `main` of the public repository. It contains:
- this report and the acceptance record;
- the phone guide and results;
- the two phone scripts;
- the card polish (`DeliveryView.tsx`, plus one line in `e2e/phase3b.spec.ts`);
- `screenshots/cards/` and `evidence/cards_polish_verification.txt`;
- the status updates to the READMEs and `CLAUDE.md`.

**Not committed (git-ignored):** `.local/phone/` (passwords, expected stops), `.env`, and the local databases.

Nothing is deployed. Phase 4 has not been started.
