# Step 3A report: rider delivery view, call and navigation links

**Date:** 19 October 2026 · **Prepared by:** Claude Code · **Status: 3A implemented and verified locally; awaiting owner review.** Phase 3 is not complete; step 3B (delivery status updates) has not started. 3A is one commit on top of `41b37f8`, pushed to the owner's private GitHub repository; nothing is deployed; ₹0 spent; Notion not accessed.

**Base:** Phase 2, accepted for local development on 19 October 2026 at `41b37f801bf6b62aa3100a4246d79d9c6f1cc515` ([record](../phase2/OWNER-ACCEPTANCE-2026-10-19.md)). **Scope:** R04, R06, R14 and R24 for the rider; tasks P3-01 (rider list and cards) and P3-02 (call and Google Maps navigation); acceptance case A15 except the on-device part ([roadmap Phase 3](../source/notion/RouteWise/04-Roadmap.md), [working flow §6](../source/notion/RouteWise/02-Working-Flow.md)). Read-only: no status changes (3B), no quick next-customer call, rerouting or same-building grouping (Phase 4), no offline storage (Phase 5), no package/dispatch confirmation.

## 1. What was built

### Rider page (`/rider`, "My deliveries")
- **One round at a time.** The round is in the URL (`?round=`), never in browser storage. The picker lists the rounds the rider takes part in or still holds orders in, newest first. Each option says "N to deliver" or "confirm your setup". A notice lists other rounds still needing the rider's confirmation, with buttons to switch to them.
- **The 2C destination card is kept unchanged** for rounds the rider takes part in (choose, save, then confirm separately). Its only change is an optional callback so the delivery view reloads after a save or confirm.
- **Route block:**
  - **Plan identity:** plan version, a **Current** badge and the time it was saved.
  - **Earlier versions:** if any exist, "It replaces version 1, which is superseded and not used". Superseded plans are never shown or used.
  - **Ends and vehicle:** the configured start and destination (depot label, or "Home (your saved location)", "Custom (your saved location)", or "Last stop — the route ends at your final delivery") and the vehicle.
  - **Distance:** the planned road distance and a "traffic-free estimate" of the time.
  - If the plan has no route for this rider, the block says so.
- **Out-of-date plan:** an alert reads "This route is out of date … The order below is the saved order from version N; it has not been re-optimized."
  - **Action:** "Ask your admin to optimize the round again". If the rider's own setup is no longer confirmed, the alert says to confirm first.
  - **Labels:** the list heading becomes "Pending deliveries — saved order (out of date)" and the first stop is labelled "Next in saved order", not "Next".
  - **Planned ends:** if the saved route was planned to different ends than the current setup, it says so.
  - **No recalculation:** nothing is recalculated or reassigned.
- **Lists:**
  - **Pending deliveries in route order:** the rider's Pending orders in the current plan's stop order. Each keeps its stop number from the plan, so "Stop 3" stays "Stop 3" when earlier stops are no longer Pending. The first is marked **Next**.
  - **Pending, not in the saved route:** the rider's own Pending orders that the current plan does not sequence for them. With no plan, they are listed by order code and the page says so.
  - **Postponed** and **Completed**, separately, each with its status label.
- **Order card:**
  - stop number, Next badge and status pill (Pending / Postponed / Completed);
  - order code, customer name, product;
  - Delivery Instructions (only when present);
  - the contact **exactly as stored**;
  - **Call** and **Navigate** (Pending and Postponed only; Completed cards have no actions).
- **Empty states:**
  - "You are not part of any round yet"
  - "No route has been planned for this round yet"
  - "No deliveries are assigned to you in this round yet"
- **Refresh** button. A 401 returns to sign-in. A response for a round that is no longer selected is ignored.

### Calling (`apps/web/src/links.ts`, `telLink`)
- The card always shows the stored contact string; only the link is normalised. The `tel:` link keeps an optional leading `+` and the digits, and needs 7–15 digits (the E.164 limit), not all zeros. No country code is guessed.
- Anything else is refused, with no link and a reason ("Calling unavailable: …"). That includes a blank contact, letters or other characters, a `+` anywhere but first, too few or too many digits.
- **Call** is a plain link the rider taps; nothing dials by itself and nothing is marked done.

### Navigation (`directionsLink`)
- **Format checked first** against Google's Maps URLs documentation (Directions action):
  - `https://www.google.com/maps/dir/?api=1&destination=<lat>%2C<lng>&travelmode=two-wheeler`;
  - `api=1` is required, `destination` may be comma-separated coordinates, the comma must be encoded, and no API key is needed;
  - `two-wheeler` is a documented travel mode, but only works where Google Maps supports it.
- **No starting point** is sent: Google Maps uses its own idea of where the rider is. RouteWise never asks for the device location.
- **No `dir_action=navigate`:** Maps opens a route preview and the rider starts navigation there.
- **Opening:** the link opens in a new tab or the Maps app, with `rel="noopener noreferrer"`.
- **Coordinates:** built only from coordinates the **server** has validated (a resolved pin inside the DU North Campus service area). The client checks them again (finite, in range, not 0,0) and writes them with 6 decimals through `URLSearchParams`.
- **Unusable location:** missing, unresolved or out-of-area gives no link, plus the server's reason ("Navigation unavailable: …").
- **On screen:** "Navigate opens Google Maps directions to the customer's pin; Google Maps chooses its own road and travel options, which can differ from the planned route and your vehicle. Neither marks a delivery done." RouteWise does not claim Google Maps follows the Valhalla route or the rider's vehicle profile.

### API (read-only; `services/api/routewise_api/routers/rider.py`)

| Endpoint | Behaviour |
|---|---|
| `GET /api/rider/delivery-rounds` | Rounds the rider takes part in **or** holds assigned orders in (for example Phase 1 data, or a rider removed from a round who still holds Completed orders), newest first. Each row has the rider's own Pending/Postponed/Completed counts, participation, confirmation state and whether a current plan exists |
| `GET /api/rider/rounds/{id}/deliveries` | The rider's own orders in that round. Details below |

The deliveries endpoint works like this:
- **Ownership:** every order comes from the `Assignment` table filtered by the signed-in rider.
- **Sequence:** comes only from the round's **current** plan rows for this rider. It is filtered by the assignment as well, so a disagreeing plan row can never bring another rider's order in.
- **Response:**
  - `sequence` (stop number plus orders), `unsequenced`, `postponed` and `completed`;
  - `plan`: version, `out_of_date` (the plan's input version against the round's), the number of superseded versions, provenance flags, and the rider's own planned route (vehicle, start and destination by kind and label, open route, distance, duration);
  - `setup`: own start and destination by kind and label, vehicle, confirmation.
- **Refusals:** a round the rider neither takes part in nor holds orders in is a 404 with the same body as a round that does not exist. Admins get 403 and signed-out callers 401.

**Minimum data per order:** id, order code, customer name, product, contact, instructions, status, and `location` (only when usable), otherwise `location_issue`. No source rows, location links, notes, locks, priority flags or versions. The response carries **no Home/Custom coordinates at all**, not even the rider's own (the destination card already shows those to the rider alone). Nothing new is logged. The existing Phase 1 `/api/rider/orders` endpoints are unchanged.

### Test seed
- `e2e_setup.py` adds one synthetic rider, `p3_nia` ("Nia"), who is never added to a round, for the "no rounds" state.

## 2. Verification (19 October 2026, this Mac)

| Check | Result | Evidence |
|---|---|---|
| API suite (`pytest -q`) | **332 passed, 1 skipped** (321 at Phase 2 + 11 new in `tests/test_rider_deliveries.py`; the skip is the opt-in live planning test) | [step3a_api_pytest.txt](evidence/step3a_api_pytest.txt) |
| Frontend type checks | **OK** | [step3a_web_typecheck.txt](evidence/step3a_web_typecheck.txt) |
| Frontend unit tests | **17 passed** (13 earlier + 4 for `telLink` and `directionsLink`) | [step3a_web_vitest.txt](evidence/step3a_web_vitest.txt) |
| Frontend build | **OK** (351 kB JS, 105 kB gzip) | [step3a_web_build.txt](evidence/step3a_web_build.txt) |
| Browser suite, recorded matrices, 1280 px + 390 px | **38 passed, 2 skipped** (Phase 1: 8; Phase 2: 20; **Phase 3: 10 = 5 tests × 2 widths**; the skips are the opt-in live Phase 2 spec) | [step3a_e2e_playwright.txt](evidence/step3a_e2e_playwright.txt) |
| Targeted backend defect checks (3A only) | **8/8 caught** | [step3a_api_defect_checks.txt](evidence/step3a_api_defect_checks.txt) |
| Targeted web defect checks (3A only) | **7/7 caught** | [step3a_web_defect_checks.txt](evidence/step3a_web_defect_checks.txt) |
| Earlier screenshots | SHA-256 of all 72 PNGs under `docs/phase1` and `docs/phase2` before and after: **unchanged** | — |

**Not rerun:** the routing-engine tests (live API planning, spike regression, Phase 0 Valhalla checks) and the opt-in live browser flow. Routing and planning behaviour did not change; 3A only reads saved plans. Their Phase 2 results stand.

### API tests (`tests/test_rider_deliveries.py`, recorded real-road matrices)
1. Each rider's `sequence` equals their route in the current plan, in order, with the plan's stop numbers. They see no other rider's orders, receive exactly the minimal fields, and the response has no Home/Custom coordinates. Start, destination, version, current, not out of date and route distances all match.
2. Instructions, a `+91 …` contact and a product are returned exactly as stored; no instructions gives `null`.
3. Postponed and Completed are listed separately, not in the sequence. The remaining Pending orders keep their saved order and original stop numbers, and the plan is reported out of date, still version 1.
4. After re-planning, only version 2 is used (`superseded_versions` 1). The test checks the two versions really differ.
5. The rider's own destination change shows the saved order as out of date, with the planned destination and the new setup kept distinct.
6. No plan gives empty lists. Orders assigned without any plan (as in Phase 1 data) appear as `unsequenced` in a round the rider does not take part in, are listed with counts, and are hidden from another rider.
7. A `needs_correction` order and an out-of-area pin get no `location`, each with its reason; the out-of-area coordinates are not returned.
8. A rider removed from a round still sees the Completed orders they hold; their setup endpoint is a 404.
9. Another rider's round equals a missing round (same 404 body, no customer data); `delivery-rounds` is empty for an outsider; an invalid id gives 422; admin gets 403 and signed out 401.
10. Defence in depth: if a plan row and the assignment disagree, the order follows the assignment and is never in the other rider's sequence.
11. No customer fields or private coordinates appear in any log record while the views are served.

### Browser tests (`apps/web/e2e/phase3.spec.ts`, both widths)
Links are inspected, never followed. Every request to `google.com`/`goo.gl` from the rider's browser context is blocked and counted, and the tests assert that count is zero (no automatic navigation, no popup).

| # | Test | Covers |
|---|---|---|
| 1 | Own route with details and links | Admin adds instructions to one order, a short contact (`12345`) to another and a `+91 …` contact to a third, and locks all three to Asha; smart plan. Asha's page: version 1 Current, start Office, destination "Home (your saved location)", traffic-free wording, the Google Maps caveat. The sequence equals her plan route **in order**, with Stop 1…n and a single **Next**. None of Bilal's order codes or customer names appear. Each card shows customer, product and the stored contact. Navigate `href` equals the documented URL for that order's coordinates, with `target=_blank` and `rel="noopener noreferrer"`. Call `href` is the normalised `tel:` (`tel:+910000000042` for `+91 00000-00042`). `12345` shows "Calling unavailable" and no Call link while still displaying "12345". The instructions are shown only on the order that has them. The Call link is keyboard-focusable and labelled "Call <customer> (<code>)". No external request; no overflow; no browser storage |
| 2 | Postponed/Completed, out of date, invalid location, superseded | After planning, the admin postpones one order, completes another and moves a third order's pin outside the service area. The rider sees the out-of-date alert ("has not been re-optimized"; "Ask your admin to optimize the round again"), the "saved order (out of date)" heading, "Next in saved order", the remaining orders in saved order from **Stop 3**, Postponed and Completed in their own sections (Completed without actions), and "Navigation unavailable … outside the DU North Campus service area" with no link. The rider then changes and saves their destination: the alert asks them to confirm first, and the planned ends are shown. They confirm. The admin fixes the pin and re-plans: after Refresh, version 2, "It replaces version 1, which is superseded and not used", no warning, the new sequence, Postponed still separate |
| 3 | Empty states | A rider with no rounds; a participating rider with no plan and no orders (destination card still shown) |
| 4 | Direct-ID attempts | Asha opens `/rider?round=<a round only Bilal is in>`: the page does not show that round, and none of Bilal's codes, customers or Custom coordinates appear. The API returns 404 for that round (same body as a non-existent round) and for Bilal's order; Asha's own delivery response has no Home/Custom coordinates and none of Bilal's orders; admin plan endpoint 403; the round is not in her list |
| 5 | Round switching and session expiry | A refresh for round A is held while the rider switches to round B. When A's answer is released, B stays on screen, in the picker and in the URL. The session is then revoked on the server; the next Refresh returns to sign-in with no deliveries shown |

**Earlier specs adjusted (navigation only, no assertion weakened):** since the rider page now shows one round at a time, four rider sign-ins in `e2e/phase2.spec.ts` now open the round under test with `?round=` (`gotoRound(rp, "/rider", …)`). One of them (the readiness-refresh test, where Asha is in two rounds) failed without this. The other three passed only because the round under test happened to be that rider's newest.

### Targeted defect checks (new 3A risks only; earlier phases not repeated)

| Injected defect | Caught by |
|---|---|
| Backend: deliveries ignore ownership (any order in the round) | API tests 1, 9 |
| Backend: another rider's round reachable | API test 9 |
| Backend: a superseded plan used for the sequence | API test 4 |
| Backend: other riders' plan rows sequenced | API test 10 |
| Backend: unusable (out-of-area) location returned as navigable | API test 7 |
| Backend: out-of-date plan not reported | API tests 3, 5 |
| Backend: Postponed orders kept in the route | API test 3 |
| Backend: private destination coordinates in the view | API test 1 |
| Web: dial link from an unvalidated contact | `links.test.ts` |
| Web: dial link for too few digits | browser test 1 |
| Web: navigation link without a usable location | browser test 2 |
| Web: out-of-date warning hidden | browser test 2 |
| Web: saved order presented as a fresh route | browser test 2 |
| Web: Completed orders get Call and Navigate | browser test 2 |
| Web: late response for another round shown | browser test 5 |

## 3. Screenshots (synthetic data; inspected at 390 px and 1280 px)

`docs/phase3/screenshots/3a/{desktop,mobile}-…png` (10 files; new folder, nothing earlier overwritten):

| File | Shows |
|---|---|
| `01-route` | Current plan, start/destination, sequence with Next, instructions, Call/Navigate, "Calling unavailable" for `12345` |
| `02-out-of-date` | Out-of-date alert, "saved order (out of date)", Stop 3 as "Next in saved order", navigation unavailable, Postponed and Completed sections |
| `03-replanned` | Version 2 replacing superseded version 1, new sequence, Postponed and Completed |
| `04-no-rounds` | Rider with no rounds |
| `05-no-plan` | Destination card plus "No route has been planned" and "No deliveries" |

Inspection found one layout problem: at 390 px the Start/Destination/Vehicle labels and values stacked on separate lines. Fixed (two columns at every width) before the final run. Repeated round names in the picker come from the synthetic imports made within the same minute (noted in 2C).

## 4. Limitations and open items

1. **No real phones yet.** The `tel:` and Google Maps links are verified by inspecting their URLs in Chromium (390 px and 1280 px). Opening the dialer and Google Maps on target Android/iOS devices is still needed: that is A15 and the P3-04 gate. No Safari, Firefox or screen-reader pass.
2. **Google Maps behaviour is Google's:** its road, its travel mode and its starting point (the device location, under Google Maps' own permission). `travelmode=two-wheeler` is documented but depends on regional support; what Maps does where it is unavailable has not been verified. RouteWise says on screen that Maps may differ from the planned route and vehicle.
3. **Contacts:** no country code is added. A 10-digit local number dials as stored digits, which depends on the phone's region settings. The importer only accepts single numbers (digits, spaces, `+ - ( ) .`), so contacts holding two numbers cannot occur today.
4. **Out of date is round-wide:** any planning input change in the round (another rider's capacity, an order edit) marks every rider's route out of date, because it compares the round's input version. This is conservative and honest, but coarse.
   - **For 3B:** a rider's own status update must not wrongly invalidate the plan. Today an **admin** status edit marks the plan out of date, as it did in Phase 2.
5. **No live updates:** the rider presses Refresh (or reloads) to see a new plan; there is no polling.
6. **"Next" is the first Pending stop in the saved order.** The quick next-customer call is Phase 4 (R15) and is not built.
7. **Destination card coordinates:** on the rider page it still shows the rider's own Home/Custom coordinates (2C behaviour, the rider only). The delivery API carries none.
8. **Same-building grouping** (Phase 4) is not built. A stop number with several orders is supported by the data but shown as separate cards.
9. **Carried over:** no retention cleanup; no offline list (Phase 5); one API process per database; local development only. Phase 2's pending decisions Q1, Q2 and Q6–Q8 remain open.

## 5. Changed files and Git state

**Git:** branch `main`. 3A is the commit after `41b37f8` (Phase 2, accepted): "Add RouteWise rider delivery view and call navigation links". Nothing is deployed.

**New:**
- `apps/web/src/links.ts`, `apps/web/src/links.test.ts`, `apps/web/src/components/DeliveryView.tsx`
- `apps/web/e2e/phase3.spec.ts`
- `services/api/tests/test_rider_deliveries.py`
- `docs/phase2/OWNER-ACCEPTANCE-2026-10-19.md`
- `docs/phase3/STEP-3A-REPORT.md`, `docs/phase3/evidence/step3a_*.txt` (7 files), `docs/phase3/screenshots/3a/` (10 PNGs)

**Modified:**
- API: `services/api/routewise_api/routers/rider.py` (two read-only endpoints)
- Web: `apps/web/src/pages/RiderPage.tsx` (rewritten around one round), `apps/web/src/api.ts` (delivery types; the unused `RiderOrder` type replaced), `apps/web/src/components/DestinationCard.tsx` (optional `onChanged`)
- Tests and tools: `apps/web/e2e/phase2.spec.ts` (four rider navigations, see above), `services/api/scripts/e2e_setup.py` (rider `p3_nia`), `services/api/tools/mutation_check.py` and `scripts/web_defect_check.py` (3A checks; the web tool also runs the Phase 3 spec and vitest)
- Docs: `docs/DEVELOPMENT.md` (3A endpoints, link format, screenshot directory), status lines in `CLAUDE.md`, `README.md` and `docs/README.md`, and an acceptance note above the original status in `docs/phase2/PHASE2-REPORT.md` and `docs/phase2/IMPLEMENTATION-PLAN.md`

**Not modified:** `docs/source/`, `spikes/`, `tests/fixtures/`, the routing core, the planning service and every earlier report body, evidence file and screenshot.
