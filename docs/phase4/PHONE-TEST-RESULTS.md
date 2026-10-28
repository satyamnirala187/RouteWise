# Phase 4 real-phone test results (OWNER-REPORTED)

**Status: owner-reported results recorded on 28 Oct 2026 (the test date and time were not supplied). These are the owner's reports, not automated observations and
not something I observed.** The automated browser tests still use mocked geolocation only. This record is evidence for the owner's acceptance of Phase 4 for local
development on 28 Oct 2026 ([record](OWNER-ACCEPTANCE-2026-10-28.md)); it is not itself the acceptance.

Nothing below includes passwords, precise coordinates, network addresses or USB device identifiers, and none should be added.

| Field | Value |
|---|---|
| Tester | owner |
| Phone model and browser | OnePlus Nord 5, Chrome (the device context reported for the Phase 3 test, [results](../phase3/PHONE-TEST-RESULTS.md)) |
| Android and Chrome versions | Not collected |
| Connection | USB with `scripts/phone-server.sh localhost` and `http://localhost:8020` through `adb reverse`, run by the owner; the Wi-Fi address was not used for location |
| RouteWise commit tested | Not supplied. The GPS result is from after the Permissions-Policy fix ([root cause and fix](GEOLOCATION-POLICY-FIX.md)) |
| Data | Synthetic test data in the isolated `routewise_phone` database (Test Rider A and Test Rider B) |

## Results

| # | Check (step 4D owner checklist, [report §6](STEP-4D-REPORT.md)) | Result (owner-reported) |
|---|---|---|
| 1 | Configured start (Office) as the route origin (item 5) | Rerouting from the Office origin succeeded, and the new route persisted after a refresh |
| 2 | Postpone (item 6) | Postponing affected only that customer. A later reroute kept the order Postponed |
| 3 | Last completed stop (item 5) | Returning an order to Pending and then completing a delivery made the last-completed-stop origin available, and rerouting from it succeeded |
| 4 | Destination change (item 8) | The page showed the previous saved destination until the change was confirmed and the route recalculated. The new destination then appeared |
| 5 | Offline (item 9) | On the loaded page, rerouting was disabled while offline and recovered after reconnecting. Refreshing the page while offline showed Chrome's offline ("dinosaur") page. Loading the app offline is Phase 5, not a Phase 4 defect |
| 6 | Location granted, real Android GPS (item 2) | After the Permissions-Policy fix, rerouting from the phone's real GPS position succeeded over USB/localhost. (Before the fix, location was blocked by the page's own policy: [GEOLOCATION-POLICY-FIX.md](GEOLOCATION-POLICY-FIX.md).) The server accepted the position, so it was inside the 100 m accuracy, 60 s age and service-area limits. The actual accuracy was not recorded |
| 7 | Shared stop (item 7) | RW-001003 and RW-001004 were explicitly grouped and locked to Test Rider B, and the admin then optimized. Rider B saw one stop with one Navigate and separate customer actions |
| 8 | Shared stop statuses (item 7) | Completing RW-001003 left RW-001004 Pending. Postponing RW-001004 then removed the stop from the active sequence. The statuses persisted after a refresh |
| 9 | Location blocked by the rider (item 3) | Explicitly blocking location produced the appropriate fallback, and last-completed-stop rerouting then succeeded. The owner reported restoring/finishing that check successfully (what exactly was restored was not specified). The wording shown was not recorded |

## Not reported (not passed, not failed)

- Wi-Fi mode showing "Location isn't available on this connection" (item 4).
- That another rider's route was unaffected by the destination change (item 8).
- Touch targets, readability and sideways scrolling (item 9).
- Location accuracy or indoor/outdoor conditions for the GPS check.
- The exact Android and Chrome versions, the commit tested and the test time.
- The 4B GPS limits (100 m, 60 s), "priority stays first", and the 4C exact-pin grouping rule were exercised only as defaults; the results do not approve them.

## Still open

- **Phase 4 was accepted for local development on 28 Oct 2026** (owner decision; production readiness is pending). Q4-6 (the real-phone secure-context route) and Q1–Q8 stay pending, and the provisional 4B and 4C defaults are not approved by these results or by the acceptance.
- **Initial backend failure:** the first full backend run at the 4D checkpoint had one failure that remains **unidentified and unreproduced** ([report §3.2](STEP-4D-REPORT.md)). These phone results do not bear on it.
- **Limits of this evidence:** one phone, Chrome only, USB/localhost only (no HTTPS or Wi-Fi location), owner-reported with no screenshots or logs recorded here. Safari and iPhone are untested.
- **Phase 5** (including offline page loading) has not started and is pending.
