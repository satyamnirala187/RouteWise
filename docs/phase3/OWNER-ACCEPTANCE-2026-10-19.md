# Phase 3 — accepted for local development

**Owner approval:** 19 October 2026. The owner reviewed the phone results and the polished delivery cards, confirmed the cards are clear and good, and asked to continue development. Phase 4 has **not** been started; it starts only when the owner asks.

**Commit:** the commit that adds this record, "Finalize RouteWise Phase 3 phone validation and delivery cards". It sits on top of:
- 3A `2b52cbc`;
- 3B `e2139c1`;
- the CI and security-review commits up to `46b17ab`.

It is pushed to `main` of the public `RouteWise` repository. Nothing is deployed.

## What the acceptance rests on

1. **Automated evidence**, as recorded in [PHASE3-REPORT.md](PHASE3-REPORT.md) §2 and §6 and the step reports ([3A](STEP-3A-REPORT.md), [3B](STEP-3B-REPORT.md)). This record adds no test runs.
2. **Owner-reported device results** in [PHONE-TEST-RESULTS.md](PHONE-TEST-RESULTS.md), on a OnePlus Nord 5 with Chrome:
   - **Original cards:** the functional checks passed. Reported: own list in order with Next; Call opened the dialer with the expected number; all four Navigate links reached the right destinations; Postpone and Return to Pending; Mark delivered to Completed; status kept after refresh and after sign-out/sign-in; server stopped.
   - **Polished cards:** the owner's visual check passed (V1).
   - These are the owner's own reports. They were not automated, and no one else observed them.

## Accepted scope

- **Rider delivery view (3A):**
  - own rounds and orders in the current plan's order, with Next;
  - Pending, Postponed and Completed sections;
  - empty and out-of-date states.
- **Links (3A):** explicit Call (`tel:`) and Google Maps directions links, built from validated values.
- **Status updates (3B):**
  - riders change the status of their own orders: Pending → Completed or Postponed, Postponed → Pending; riders cannot reopen Completed;
  - ownership is re-checked;
  - conflicts, retries and repeated requests are handled safely;
  - `route_version` separates delivery progress from route invalidation.
- **Delivery-card clarity polish:** visual only, no behaviour change.
- **Phone-test tooling (local only):**
  - `phone_setup.py` resets only `routewise_phone`;
  - `phone-server.sh` serves the app on the Wi-Fi address while PostgreSQL stays on 127.0.0.1.

The route-plan summary and version card is kept unchanged at the owner's request.

## Local development only

This is **not** production acceptance. Not performed:
- deployment, HTTPS or backups;
- iPhone/Safari, Firefox or other Android devices and browsers;
- a screen-reader pass, or keyboard use on a phone;
- load testing;
- a full delivery round on a phone (two of four stops were changed);
- offline use.

**Phone-test limits:**
- The server used plain HTTP on a trusted Wi-Fi, with cookies not marked Secure.
- In development mode the server also exposed the API docs page on that address.

## Not supplied or not run (left open, not inferred)

- **Not supplied:** phone OS version, Chrome version, exact test time, the commit tested, Google Maps app or browser, the travel mode shown.
- **Not reported:** check #4 (synthetic contacts not dialled).
- **Optional check not run or not reported:** #12, Test Rider B seeing only their own orders. Cross-rider refusal is covered by automated API and browser tests only.

## Still open (not decided by this approval)

- **Owner decisions:** Q1 (the replanning restriction, which is not built), Q2, Q6, Q7 and Q8 from Phase 2.
- **Limitations listed in PHASE3-REPORT §4:**
  - Google Maps chooses its own road and travel mode; two-wheeler mode depends on the region.
  - No country code is added to contacts.
  - No offline queue (Phase 5).
  - No quick next-customer call, reinsertion or rerouting (Phase 4).
  - "Out of date" stays round-wide.
  - The admin plan view has no per-stop status.
  - No live refresh.

Notion remains paused. No tracker update was prepared or applied with this record.
