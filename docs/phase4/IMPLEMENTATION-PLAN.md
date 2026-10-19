# Phase 4 implementation plan: quick call, rerouting and shared stops

**Status: step 4A committed (`e40e0b0`), awaiting review ([report](STEP-4A-REPORT.md)); step 4B committed ("Add RouteWise individual rider rerouting", after `e40e0b0`), awaiting review ([report](STEP-4B-REPORT.md)); 4C and 4D not started. Phase 4 is incomplete.**

The owner authorized **step 4A**, then **step 4B**, on 19 October 2026, each on its own. For 4B the owner set local implementation defaults for Q4-2, Q4-3, Q4-4, Q4-5 and Q4-7 (§4). They are **provisional and configurable**, not separately approved permanent product decisions. Q4-1 (grouping) and Q4-6 (phone secure context) remain pending, and 4C and 4D each need their own approval.

| | |
|---|---|
| Date | 19 October 2026 |
| Prepared by | Claude Code |
| Baseline | Phase 3, accepted for local development at `3fa1e40435981e98f040d896ca45b3ef8397fc5c` ([record](../phase3/OWNER-ACCEPTANCE-2026-10-19.md)) |
| Approval | 4A and 4B authorized by the owner (19 Oct 2026). 4C and 4D not approved. Q4-2/3/4/5/7 used as provisional 4B defaults; Q4-1 and Q4-6 pending |

**Constraints:**
- ₹0, using local Valhalla only (`spikes/valhalla/data/valhalla_tiles`).
- No paid API, public demo server, deployment, map tiles or new runtime dependency.
- Notion is paused.

**Steps:**

| Step | What | Mostly |
|---|---|---|
| **4A** | Quick next-customer call | UI only |
| **4B** | Individual rerouting and endpoint-change recalculation | server and API |
| **4C** | Same-building stops | grouping, planner, admin |
| **4D** | Integration and device verification | rider screens, browser tests, phone checks |

Each step is committed and reviewed separately.

## 0. What the accepted requirements already settle

| Source | What it settles for Phase 4 |
|---|---|
| R15, task P4-01, A17 | A quick call to the next customer before travelling. The call action follows the next active order. |
| R17, R19, D11, P4-02, A18 | An unavailable customer can be Postponed, and the rider *may* reroute their own remainder. Other riders' packages and routes stay as they are. |
| R18, A19 | The reroute origin is either the actual current location, or the last completed stop explicitly selected. With neither, the rider confirms a pin or their configured start ([working flow §7](../source/notion/RouteWise/02-Working-Flow.md)). Never pretend GPS is available. |
| R20, D06, P4-04, A21 | Same-building customers share one navigation stop but keep distinct orders and statuses. Capacity counts orders. Proximity alone never groups (Phase 0 tests). |
| R22 | Reoptimization requires connectivity. There is no offline reroute (offline is Phase 5). |
| R23, P4-03, A20 | An endpoint change after planning triggers **only that rider's** recalculation. A failed result keeps the last valid plan, visibly awaiting recalculation. This replaces the Phase 2 interim answer to Q2 ("plan marked out of date") for the rider's own route. |
| D05 (proposed) | Priority means the first active order on that rider's route. |
| D08 (approved 13 Oct) | Postponed orders keep their rider. An explicit return to Pending makes them eligible for reinsertion. Nothing is retried automatically. |
| [Privacy](../source/notion/RouteWise/07-Privacy.md) | Request location only for the action that needs it, with no continuous tracking. Precise coordinates are redacted from logs and evidence. |
| R16 | Statuses remain exactly Pending / Postponed / Completed. "Recalculating", "awaiting recalculation" and similar are display metadata, never statuses. |

**Not in scope:**
- mandatory package or dispatch confirmation, or any new status;
- analytics, a postponed-orders dashboard or a balanced-workload mode;
- GPS tracking (no `watchPosition`, no position history);
- offline storage or queues (Phase 5);
- maps or tiles (Q8);
- handing orders over between riders.

Q1 (whether the admin may re-optimize a whole round after issue) stays pending and is not built. §2.6 explains how it interacts with rider routes.

## 1. Baseline at `3fa1e40` (what Phase 4 builds on)

- **Round plans are round-wide and immutable.** A plan is one `route_plans` row (`is_current`, `version`, `route_version`), with one `plan_routes` row per rider and `plan_orders` rows (`active` with `stop_seq`, or `postponed`/`completed` held). An admin plan commit supersedes the previous plan as a whole (`planning.commit_plan`).
- **Ownership** is `assignments.order_id → rider_id` (one owner per order). Only plan commits write it.
- **Validity split (3B):**
  - `delivery_rounds.input_version` changes with every planning-input change, so an in-flight solve becomes stale.
  - `delivery_rounds.route_version` changes with everything except a rider's own delivery progress. When it differs from the plan's, the whole plan is "out of date".
  - **Conflict with R23:**
    - A rider's destination change (`riders.bump_config`) bumps the **round-wide** `route_version`, so one rider's change marks every rider's route out of date.
    - A rider's confirmation (`confirm_setup` → `bump_round_input`) does the same.
- **Runs:** one active planning run per round (`uq_planning_runs_one_active`), in a bounded in-process worker. The snapshot is held in memory, no transaction is open during the solve, and the commit re-checks under the depot → round locks.
- **Grouping is prepared but inactive:**
  - `orders.building_id` exists but nothing sets it, and `OrderSnap.building_id` is always `None`.
  - The ported planner already groups by `building_id` + location + lock (`routing/planner.build_stops`) and merges consecutive building stops (`merge_building_stops`).
- **Spike reroute:** `spikes/routing/routewise_spike/reroute.py` (origin choice, a rider-only re-solve, provider failure keeps the last plan) was **not** ported. In the spike a reroute makes a whole new plan version; the app will not (§2.1).
- **No completion time:** `orders` has no `completed_at`, so the "last completed stop" cannot be determined today.
- **Delivery view:** `GET /api/rider/rounds/{id}/deliveries` already groups orders by `stop_seq`, so several orders can share one stop. Next is the first stop.
- **Status updates (3B)** lock order → round and re-check ownership under the round lock.
- **No geolocation code exists.** The phone-test server is plain HTTP on a Wi-Fi address, which is **not a secure context**, so browsers withhold geolocation there (§2.9).
- **Recorded test matrices** include a public `gps_r1` point, usable as a mocked "current position" in tests.

## 2. Core design

### 2.1 Rider route revisions layered on immutable round plans

**Approach:** keep `route_plans`, `plan_routes` and `plan_orders` exactly as they are, and never rewrite them. Add **rider route revisions** that belong to one rider and one round plan:

```
route_plans (round-wide, immutable)          ← admin "Optimize all routes"
  └─ plan_routes / plan_orders (per rider)   ← revision 0 of each rider's route
       └─ route_revisions (per rider, per plan, numbered 1, 2, …)  ← rider reroutes / endpoint changes
            └─ revision_orders (that rider's active Pending sequence)
```

**A rider's effective route** in a round:
1. Take the round's current plan *P*.
2. If *P* has a current revision for that rider, use that revision.
3. Otherwise use the rider's `plan_routes`/`plan_orders` in *P*.

When the admin commits a new round plan, every revision of the old plan stops being effective automatically, because it hangs off the superseded plan. Nothing is deleted.

**Why not new round plan versions per reroute (the spike's approach)?**
- **No cross-rider writes:** a rider's reroute would have to copy every other rider's routes into a new round version, so one rider's action would write other riders' data.
- **Admin history stays readable:** the admin's plan history would fill with rider-made versions.
- **No needless contention:** the commit would collide with the round's single-current-plan index.

Revisions write only the requesting rider's rows, so isolation can be proven by checking that every other row is untouched.

### 2.2 Schema (migration `0005_phase4b_rider_routes`, step 4B)

| Change | Purpose |
|---|---|
| `round_riders.route_version INT NOT NULL DEFAULT 1` | Rider-scoped route validity (§2.3) |
| `plan_routes.rider_route_version INT NOT NULL DEFAULT 1` | The rider's `route_version` when the round plan was committed |
| `orders.completed_at TIMESTAMPTZ NULL`, `orders.completed_by UUID NULL → users` | Set on any transition into Completed and cleared if an admin reopens the order. Rows that were Completed before the migration stay NULL ("time unknown") and are never offered as a fallback origin |
| `planning_runs`: `scope` (`round`/`rider`, default `round`), `rider_id`, `base_plan_id`, `origin_kind` | Reuses the existing worker, recovery and expiry for rider runs. The single active-run index becomes two partial unique indexes: one active **round** run per round, and one active **rider** run per (round, rider) |
| `route_revisions` | See below |
| `revision_orders` (`revision_id`, `order_id` PK; `stop_seq ≥ 1`) | The rider's active Pending sequence only. Postponed and Completed orders keep their ownership through `assignments`, exactly as now |

**`route_revisions` columns:**
- **Identity:** `id`, `round_id`, `rider_id`, `plan_id` (FK `(plan_id, rider_id)` → `plan_routes`), `revision` (unique per plan and rider), `run_id` (unique).
- **Currency:** `is_current`, with a partial unique index on (`plan_id`, `rider_id`) where current.
- **Why and from where:**
  - `trigger`: `rider_request` or `endpoint_change`;
  - `origin_kind`: `current_position`, `last_completed_stop`, `configured_start`, or `entered_position` if Q4-3 is approved;
  - `origin_order_id`: only for `last_completed_stop`.
- **Route data:** `vehicle`, `profile`, `capacity`, `endpoint_kind`, `open_route`, `road_distance_m`, `road_duration_s`.
- **Validity record:** `rider_route_version`, `round_route_version`, and `input_fingerprint` (keyed HMAC of the rider-scoped input).
- **Audit:** `provenance` (no coordinates), `created_by`, `created_at`, `superseded_at`.

**No column anywhere stores a rider's position.** Home/Custom coordinates continue to live only in `rider_endpoints`.

### 2.3 Per-rider versus round-wide versions

| Change | `input_version` (round) | `route_version` (round) | `route_version` (that rider) |
|---|---|---|---|
| Rider marks Completed / Postponed / returns to Pending (3B) | +1 | — | — |
| **Rider changes own destination (R23)** | +1 | — *(was +1)* | **+1** |
| **Rider confirms own setup** | +1 | — *(was +1)* | — |
| Admin: participation, vehicle, capacity, start; depot coordinates; account deactivation | +1 | +1 | — |
| Admin order edits: pin, status, lock, priority, stop group (4C) | +1 | +1 | — (Q4-5) |
| Rider reroute commit | — | — | — (records the current value) |
| Admin round plan commit | — | — | — (records every rider's current value) |

**Validity of a rider's effective route (computed at read time, nothing stored):**
- **Round out of date:** the plan's `route_version` ≠ the round's. This is the 3B behaviour, unchanged. The admin must re-optimize.
- **Awaiting recalculation (rider):** the effective route's `rider_route_version` ≠ the rider's current value, for example after a destination change. Other riders are unaffected.
- **Needs reinsertion:** the rider has Pending orders that are not in the effective sequence, for example a returned Postponed order. The fix is a reroute.
- **Progress since plan:** this keeps its 3B meaning.

**The 3B rule is kept:** every status change bumps `input_version` and never bumps `route_version`.

**Unrelated riders never reconfirm** because of another rider's endpoint change. Confirmations are already per rider (`config_version`). With this table, their routes are no longer marked out of date either.

### 2.4 Reroute run lifecycle

Same shape as `planning.py`. **No transaction is open while matrices or the solver run.**

**1. Request** (`POST`, rider session and CSRF token):
- Take the locks in the existing order: depots `FOR SHARE` → round `FOR UPDATE` → own `round_riders` row `FOR UPDATE`.
- **Refuse** with a coded error when:
  - the rider is not participating (404, like a missing round);
  - there is no current plan, or no route for the rider in it;
  - the round is out of date;
  - a round run is active (`ROUND_REPLANNING`);
  - the rider's own setup is unconfirmed;
  - there are no Pending orders;
  - the origin is unusable;
  - another rider run of the same rider is active (409 with that run's id).
- **Capture a rider-scoped snapshot**, held in memory only:
  - the base plan id;
  - the round and rider route versions;
  - the rider's vehicle and capacity;
  - the confirmed endpoint, including Home/Custom coordinates;
  - the rider's own orders through `assignments` (id, status, version, pin, lock, priority, `building_id`, `completed_at`/`completed_by`);
  - the origin.
- Store a `queued` rider run with the keyed fingerprint and submit it.

**2. Solve (worker):**
- Compute a one-profile matrix over: origin, the rider's Pending stop locations, and the endpoint if it is not Last stop.
- Build the stops (grouping per 4C) and solve one vehicle with OR-Tools.
- A priority stop goes first (§2.8).
- The plan is rejected unless `real_road` holds. A missing edge never counts as zero.

**3. Commit:**
- Take the same locks plus the run row.
- The commit is **`stale` (nothing written)** unless all of these still hold:
  - the base plan is still current;
  - the round `route_version` and the rider `route_version` are unchanged;
  - the recaptured rider-scoped fingerprint matches;
  - the account is still active.
- Then, in one transaction:
  - supersede the rider's previous revision for this plan, if any;
  - insert the new revision and its `revision_orders`;
  - run an independent re-read: every sequenced order is owned by the rider and Pending, and the set equals the snapshot's Pending set;
  - check that `assignments` is unchanged: a query over the whole round, compared before and after;
  - check that no `plan_routes`/`plan_orders` row and no other rider's revision was written. Tests assert this at row level.
- Mark the run `succeeded`.

**4. Read:**
- `GET /api/rider/reroutes/{run_id}` is visible to its own rider only; any other rider gets the same 404 as a missing run.
- The delivery view returns the effective route.

**Limits:**
- Worker slots are shared with admin runs. When they are full, the rider gets 503 "busy, try again". Requests are never queued without a bound.
- The existing per-run size limits apply.
- A separate rider-run time limit: `RerouteLimits.solve_seconds`, default 10 s (`ROUTEWISE_REROUTE_SOLVE_SECONDS`). It is a ceiling: a four-stop recalculation took about 0.1 s on the local tiles ([4B report](STEP-4B-REPORT.md)).

### 2.5 Ownership checks at each point

| Point | Check |
|---|---|
| Request | Own participating round (else the same 404 as a missing round). Orders only through `assignments.rider_id = me`. A `last_completed_stop` origin must be the rider's own order in this round, Completed, with `completed_by` = the rider's user and a resolved pin. |
| Snapshot | Only own orders are read; nobody else's orders, endpoints or locations. |
| Commit | Under the round lock: ownership is re-read through the fingerprint (owner ids are part of it). An order reassigned meanwhile makes the run stale. Post-write re-read and assignment-equality assertion. |
| Response | Only own runs and revisions are returned. Admin views name riders, kinds and order codes, never origins or Home/Custom coordinates. |

### 2.6 Races

| Race | Outcome |
|---|---|
| Admin round run active, rider asks to reroute | Refused (`ROUND_REPLANNING`): "Your admin is replanning the round; try again when it finishes." |
| Rider run in flight, admin starts a round run | Allowed; the admin has authority. **(a)** If the reroute commits first, its revision is superseded when the admin plan commits; the plan summary lists "rider reroutes superseded" by rider name, and the rider sees the new plan with a notice. **(b)** If the admin plan commits first, the reroute ends `stale` ("Your admin replanned the round. Nothing was saved."). |
| Rider status update during own reroute | The reroute ends stale (the fingerprint includes own statuses). The UI disables status actions while a reroute runs (one action at a time, as in 3B). |
| Another rider's status update or reroute | Independent. Not stale, nothing waits beyond the short round lock, no rows shared. |
| Admin edits the rider's orders, config or endpoint during a reroute | Stale (fingerprint or route version). |
| Admin edit elsewhere that bumps the round `route_version` | The round becomes out of date, and the reroute ends stale and is refused until the admin re-optimizes. This is conservative; see Q4-5. |
| Two reroute requests from the same rider (double tap, two tabs) | The partial unique index allows one. The second gets 409 with the active run id, and the UI follows that run. |
| API restart mid-run | `recover_interrupted_runs` marks rider runs `interrupted`, never succeeded. The last valid route stays. |

**Interaction with Q1 (pending, not built):** an admin re-optimization mid-round still plans every rider from their configured Office/Warehouse start. It supersedes rider revisions, and today it may move Pending orders between riders. Phase 4 does not change that.
- **Effect on riders:** after such a replan, each rider can reroute from their actual position.
- **Owner decision:** whether whole-round replanning should be restricted mid-delivery remains Q1.

### 2.7 Origins and location privacy

**Current position:**
- **Read:** one reading via `navigator.geolocation.getCurrentPosition` with `enableHighAccuracy: true`, `maximumAge: 0` and a timeout of about 15 s, requested **only when the rider taps "Use my current location"**.
- **Sent to the server:** lat, lng, accuracy and the age of the fix.
- **Refused** (`POSITION_UNUSABLE`, with fallbacks offered) when:
  - the accuracy is worse than **100 m**;
  - the fix is older than **60 s**;
  - the values are non-finite;
  - the position is outside the DU North Campus service area, which the local tiles cover.

  These thresholds are a proposed default (Q4-2).
- **Fallback:** a position Valhalla cannot route from gives `UNROUTABLE_ORIGIN` and offers the fallbacks.
- **Honesty about freshness:** the server cannot prove a fix is fresh. The client never caches positions (`maximumAge: 0`, nothing in storage), and every revision and screen states its origin kind.

**Last completed stop:**
- Offered only when one exists, and **only when the rider selects it**. It is never chosen automatically.
- It is labelled "From your last completed stop: RW-… (customer name), not your current position".

**No completed stop:**
- The rider explicitly picks **"From the Office/Warehouse (my configured start)"**, labelled as such.
- Entering a position by coordinates or a Google Maps link (a "pin" without map tiles) is Q4-3.
- Nothing is assumed.

**Retention:**
- A submitted position exists only in request memory and in the worker's in-memory snapshot.
- It is **never** written to the database, logs, run errors, fingerprints, provenance, responses or test evidence.
- Revisions keep only the origin kind (plus the order id for the last-completed-stop fallback).
- `test_migrations_privacy` gets a check that a submitted test position's coordinate strings appear in no table and no captured log.
- Retention otherwise follows D10 (30 days). Revisions hold no coordinates. The retention purge itself is still a known gap from earlier phases.

### 2.8 Endpoints, open routes, priorities and held capacity

**Endpoint:**
- The reroute ends at the rider's **current confirmed** endpoint: Office/Warehouse by depot, or Home/Custom from `rider_endpoints`, in memory only.
- An unconfirmed change is refused (`NOT_CONFIRMED`: "Confirm your setup first").

**Vehicle profile:**
- The profile comes from the rider's current `round_riders.vehicle` (`motor_scooter`/`motorcycle`, never bicycle or car).
- If the admin changes the vehicle after the plan, the round becomes out of date (§2.3), so a stale profile cannot be used.

**Last stop:**
- The route is open: it ends at the last delivery.
- Reported distance and duration exclude the virtual sink arc, as in 2B.
- When nothing is Pending, there is nothing to route (`NOTHING_TO_REROUTE`).

**Priority (D05):**
- If the rider still holds a Pending first-priority order, its stop stays **first** in the rerouted sequence (Q4-4 confirms this mid-route).
- Two Pending priority orders for one rider can only arise from an admin edit, which makes the round out of date; the solver also refuses `PRIORITY_CONFLICT`.

**Held capacity (D06):**
- A reroute moves no ownership, so the rider's Pending + Postponed + Completed count does not change.
- The commit still asserts that count ≤ `round_riders.capacity`. A capacity cut below holdings is an admin change that makes the round out of date.

**Postponed reinsertion (D08):**
- **Before a reroute:** an explicit return to Pending puts the order back at its saved stop if the *effective* route sequenced it (the 3B rule, now applied to effective routes). Otherwise it appears as "Not in your route".
- **On reroute:** every own Pending order is included, so a returned order is reinserted.
- Nothing returns automatically.

### 2.9 Secure context and honest device testing

**The constraint:**
- Browsers expose geolocation only in a **secure context** (HTTPS, or `http://localhost`).
- The Phase 3 phone server (`http://<Wi-Fi address>:8020`) is not one, so geolocation is absent or denied there.
- The app checks `window.isSecureContext` and whether `navigator.geolocation` exists, and says "Location isn't available on this connection", then offers the fallbacks.

**Real phone, ₹0 options** (Q4-6):
- **(a) Default:** USB debugging with `adb reverse tcp:8020 tcp:8020`. The phone opens `http://localhost:8020`, which is a secure context.
  - **Cost and setup:** no certificate, and the server can stay bound to 127.0.0.1. Needs a USB cable and Android platform-tools, which are free.
  - **Script change:** `scripts/phone-server.sh` gets a localhost mode with the matching allowed origin.
- **(b)** Chrome's "insecure origins treated as secure" flag on the phone, for the test origin only.
- **(c)** Local HTTPS with a locally generated CA installed on the phone.
- **Not used:** no public tunnel, hosted service or deployment.

**Mocked versus real:**
- Browser tests use Playwright geolocation emulation (`grantPermissions` + `setGeolocation` at the recorded `gps_r1` point) and a scripted stub for timeout and unavailable cases.
- Evidence labels these **"mocked geolocation"**.
- Only the owner's phone checks count as real-device location results, recorded as owner-reported, as in Phase 3.

**Coverage limit on a real phone:**
- A real GPS reroute can succeed only **inside the local tile coverage** (the DU North Campus buffer).
- Elsewhere, the real-device check can only confirm the refusal and the fallbacks.

## 3. Steps

### 4A: Quick next-customer call

*Implemented as below on 19 October 2026 (awaiting review). The owner's 4A instructions narrowed the panel to the call and "Customer unavailable", so Navigate and Mark delivered stay on the stop cards, not in the panel.*

**User-visible behaviour**
- **Next-customer panel:**
  - **Where:** directly above the existing Route card, which stays **unchanged** at the owner's request. On a phone the rider's setup card is still above it.
  - **What it shows:** the stop number, a "Next" label, the customer name and product, the order code, a large **Call ⟨name⟩** button and **Customer unavailable**.
  - **Note under the buttons:** calling only opens the dialer and records nothing; "Customer unavailable" postpones this order only, and it can be returned to Pending later.
- **Which order is "next":**
  - The first Pending order of the first saved stop, as shown in the server-confirmed view.
  - With several orders at one stop, the first in the server's order, with "N more Pending customers at this stop". Several orders per stop only arise after 4C.
  - Postponed and Completed orders are never next.
  - If the saved route is out of date: "Next in saved order", plus a line saying it is not a newly optimized route.
  - Pending orders outside the saved sequence are **never** picked. The panel explains why there is no next customer: no plan yet, or not in the saved route.
- **Calling:**
  - Tapping Call opens the dialer only.
  - **No** request is sent, no answer or availability is recorded, and there is no timer or automatic action.
- **Customer unavailable:**
  - It sends the existing 3B Postpone request for that order only, sharing the page's single in-flight save, version check, conflict handling and retry with the cards.
  - The panel moves to the next customer only when the server-confirmed view arrives. The page's status line says "RW-… saved as Postponed."
  - An uncertain network result keeps the same customer and shows the retry in the panel.
- **Contacts that can't be dialled:** the panel shows the existing "Calling unavailable" reason, and Customer unavailable stays available.
- **Empty states:**
  - no plan yet;
  - Pending orders not in the saved route;
  - only Postponed orders left;
  - all completed.
- **Not offered in 4A:**
  - no recalculate or reroute button, inactive or otherwise;
  - no GPS or grouping;
  - no new availability status.

**Schema / API / UI**
- **Schema / API:** none.
- **UI:**
  - a `NextCustomer` panel in `DeliveryView.tsx`;
  - a pure function `nextDelivery(view)` in `src/next.ts`;
  - reuse of `telLink` and the page's `StatusActions`.
- **Unchanged:** delivery cards and the Route card.

**Dependencies:** Phase 3, accepted.

**Acceptance tests** (actual results in the [4A report](STEP-4A-REPORT.md))
- **Unit (`nextDelivery`):**
  - first stop; multi-order stop count;
  - Postponed or Completed never picked;
  - out-of-date flag;
  - unsequenced orders never picked;
  - every empty state.
- **Browser (1280 and 390 px, `e2e/phase4a.spec.ts`):**
  - correct customer and exact `tel:` target, with the panel above the unchanged Route card;
  - a Call tap (dialer suppressed by the test) sends no request and changes no status or version;
  - Customer unavailable postpones only that order;
  - the panel waits for the server: every status button is disabled, and a duplicate tap sends nothing;
  - uncertain result and retry, with a lost answer recognised as already done;
  - a conflict overwrites nothing, a Completed order is never next, and the stale label appears;
  - empty states, and an undialable contact;
  - another rider's orders never shown;
  - round switching with a late answer;
  - session expiry.
- **Defect checks:** targeted ones in `scripts/web_defect_check.py`.
- **Screenshots:** in `docs/phase4/screenshots/4a/`.

**Risks, defaults and decisions**
- **Duplicate controls:** "Customer unavailable" and the stop card's Postpone act on the same order through the same state, so they can't diverge.
- **No call outcome:** knowing whether the customer answered is not possible and is not inferred.
- **Priority within a stop:** the rider view does not carry the first-delivery flag. Within-stop priority ordering is therefore 4C work, alongside shared stops.

### 4B: Individual rerouting and endpoint-change recalculation

*Implemented on 19 October 2026 (committed, awaiting review; [4B report](STEP-4B-REPORT.md)). Where the build differs from or adds to this plan:*
- *The delivery view keeps `plan.route` as the admin plan's route and adds `plan.rider_route`, the effective route. The route summary card is unchanged.*
- *The admin plan endpoint adds `rider_route` per rider. The admin plan page shows two one-line notes: "awaiting recalculation", and "recalculated by the rider … the stops below are the saved plan". Without them, a rider's destination change would have removed the admin's only visual signal.*
- *`configured_start` is accepted only when the rider has no recorded completed stop (working flow §7).*
- *`last_completed_stop` must name the order the rider was shown; a newer completion gives `ORIGIN_CHANGED`.*
- *Only completions recorded by the rider's own account count; an admin's completion never does.*
- *The rider-scoped fingerprint leaves out order versions, so customer-text edits never make a reroute stale.*

**User-visible behaviour** (through the API in 4B; screens in 4D)
- **Reroute:**
  - A rider can recalculate **only their own remaining Pending orders**, from:
    - their current position;
    - an explicitly selected last completed stop;
    - with neither available, their explicitly selected configured start.
  - Completed history, Postponed ownership, every assignment, and every other rider's saved route and revisions stay exactly as they were.
- **Endpoint change after planning:**
  - It marks only that rider's route "awaiting recalculation: ends at your previous destination".
  - After the rider confirms, the reroute uses the new endpoint. No other rider is marked out of date or asked to reconfirm.
- **Failure:** the last valid route is kept and labelled "Not recalculated", with the reason.
- **Connectivity:** a reroute is a server action, so offline means it is unavailable (R22).

**Schema / API / UI**
- **Schema:** migration 0005 (§2.2) and the version classification change (§2.3: `choose_destination` and `confirm_setup`).
- **Routing:** port `reroute.py` into `routewise_api/routing/reroute.py`:
  - origin choice;
  - a rider-only solve;
  - the invariant check;
  - parity tests against the spike's `test_reroute_building.py` scenarios, extending `test_routing_parity.py`.
- **Planning service:** `planning.py` gains the rider-scoped snapshot, fingerprint and commit (§2.4), and rider runs in the existing worker.
- **API:**
  - `POST /api/rider/rounds/{round_id}/reroute`, body `{origin: {kind: "current_position", lat, lng, accuracy_m, age_s} | {kind: "last_completed_stop"} | {kind: "configured_start"}, expected_plan_version, expected_revision}`:
    - returns 202 `{run_id}`;
    - coded 404, 409 or 422 refusals (§2.4);
    - CSRF and Origin are enforced.
  - `GET /api/rider/reroutes/{run_id}`, own runs only.
  - The delivery view adds, per round:
    - `route.revision` (`number`, `origin_kind`, `origin_label`, `created_at`, `trigger`);
    - `awaiting_recalculation` with its reason;
    - `not_in_route` count;
    - `last_completed_stop` (order code and customer, for the chooser);
    - `reroute_in_progress` (run id);
    - effective distances.
  - Admin `GET /rounds/{id}/plan` shows each rider's effective route source (plan or revision n, origin kind, time) and the superseded-reroute summary. It never includes positions.
- **UI:** none beyond reading new fields (4D).

**Dependencies:** 4A (for P4-01 → P4-02 ordering; there is no code dependency); Q4-2, Q4-3, Q4-4, Q4-5 and Q4-7 answered or defaults accepted.

**Acceptance tests** (pytest on PostgreSQL with the recorded DU matrices; the `gps_r1` point is the mocked current position)
- **A18:** Postpone, then reroute. Only the rider's sequence changes. Verified by row-level equality of every other `plan_routes`/`plan_orders`/`route_revisions` row and of the whole round's `assignments`. Postponed and Completed keep their owner and stay out of the sequence.
- **A19:**
  - a current position is used and recorded as `current_position` only;
  - with no position, the last completed stop is used only when requested;
  - with no completed stop, `NO_COMPLETED_STOP` is returned, and configured start succeeds only when explicitly chosen;
  - a stale fix, poor accuracy, out-of-area or unroutable origin is refused;
  - an admin-completed order is not offered as the rider's last stop.
- **A20:** Home → Warehouse after planning:
  - only that rider's `route_version` moves; the round's does not;
  - other riders are not out of date and not unconfirmed;
  - the reroute ends at the Warehouse, and Completed orders are retained.
- **Reinsertion:** a Postponed order returned to Pending without a saved stop is listed as not in the route, then sequenced by the reroute.
- **Priority and open routes:**
  - a priority Pending order stays first;
  - a Last stop reroute is open, and its distance excludes the sink.
- **Races (hooks `after_solve` / `before_write`):** every row of §2.6, including:
  - the admin plan committing first, which makes the reroute stale;
  - the reroute committing first, which is superseded and reported;
  - own status changes during a solve, which make it stale;
  - another rider's change, which does not;
  - a double request, which gets 409 with the run id;
  - a restart, which marks the run interrupted.
- **Isolation:**
  - another rider's round, run id or completed order as origin gives the same 404 as a missing one;
  - an order reassigned between snapshot and commit makes the run stale;
  - nothing is written for refusals.
- **Failure:** provider failure or unroutable origin gives a failed run, an unchanged effective route, and `awaiting_recalculation` where applicable.
- **Privacy:** submitted coordinates appear in no table, log or response.
- **Regression:**
  - the 3B split: a status change bumps `input_version` only;
  - all existing API, routing and browser suites pass.
- **Opt-in live test:** a reroute on the real local tiles (`ROUTEWISE_LIVE_TESTS=1`).

**Risks, defaults and decisions**
- **Two-level validity:** it is new and subtle, so the delivery view and admin view must agree. Default: both use one helper.
- **Conservative staleness:** an unrelated admin edit blocks reroutes round-wide until re-optimization (Q4-5 could narrow this).
- **Snapping:** Valhalla snaps GPS points to the nearest road edge. A far snap gives a wrong first leg. Q7, the snap-distance guard, is still pending from Phase 2. Default: reuse the unroutable check; no snap guard until Q7 is decided.
- **Solve time:** single-rider solves are expected to be fast at local sizes. They will be measured and recorded.

### 4C: Same-building stops

**User-visible behaviour**
- **Admin, on the Orders page:**
  - Orders of the same round with **identical resolved pins** are marked "Same pin as RW-…".
  - The admin can **Group as one stop** or **Ungroup**.
  - **Pins that are merely nearby are never suggested or grouped.**
  - Editing a grouped order's pin removes that order from its group, with a visible notice.
  - Grouping changes are planning input, so a saved plan becomes out of date, as with other admin order edits.
- **Rider:**
  - A grouped stop is **one navigation stop**: one Navigate to the shared pin.
  - It holds separate customer cards, each with its own Call, product, contact and status.
  - Completing one order leaves the others unchanged.
  - The stop remains Next while any of its orders is Pending.
  - Postponed orders from it move to the Postponed section.
  - The rider screens for this land in 4D. The API exposes it in 4C.

**Grouping rule** (conservative; Q4-1 confirms it)
- A group is admin-confirmed and covers ≥ 2 orders in one round with **exactly equal stored coordinates**.
- The id is a server-generated opaque `building_id`; no address text is used.
- A group is never inferred from distance, address text or customer names.
- A different pin always ends membership.
- An admin can keep identical pins as separate stops (separate entrances) simply by not grouping them. That choice is preserved, matching the Phase 0 test "manually split building is not merged".

**Capacity, ownership and priority**
- **Capacity (D06):** a group of *n* orders demands *n* capacity units.
- **Splitting:** if a group exceeds the largest rider capacity, or its orders carry different owner locks, the planner splits it (existing `build_stops`). Each rider then gets one stop at that building (P4-04: "one stop per applicable rider").
- **Priority (D05):** if any order in a group is first-priority, the whole stop is that rider's first stop. The priority order is listed first within it. Two priority orders in one group make one priority stop, not a conflict.
- **Reroutes** group the rider's own Pending orders the same way.
- **Partial completion:** the remaining Pending orders of a partly delivered building stay one stop.

**Schema / API / UI**
- **Schema:** migration `0006_phase4c_stop_groups`:
  - an index on (`round_id`, `building_id`);
  - a length check;
  - documented semantics (no new table).
- **Planning:** `OrderSnap.building_id` comes from the database, and both fingerprints include it.
- **API:**
  - `POST /api/admin/rounds/{round_id}/stop-groups` `{orders: [{id, version}]}` creates a group. Rules: all in the round, resolved, inside the area, identical pins; versions are checked; the round is bumped.
  - `DELETE /api/admin/orders/{order_id}/stop-group` `{version}` ungroups one order. A group left with one order dissolves.
  - The admin orders list adds `stop_group` and `same_pin_as` (order codes only).
  - The rider delivery view's stops add `shared` and `customers`. There is one location per stop, identical by construction.
- **UI:** admin Orders page badges and actions only.

**Dependencies:** 4B, for grouping inside reroutes; Q4-1.

**Acceptance tests**
- **Grouping:**
  - identical pins are grouped only after the admin confirms;
  - nearby, non-identical pins are never suggested or grouped;
  - a pin edit splits the order out;
  - a group across rounds is refused.
- **Planner:**
  - one navigation stop with *n* capacity units (A21 setup);
  - a capacity split and a lock split give one stop per rider;
  - priority inside a group.
- **A21:** complete one order of a two-order stop:
  - the other stays Pending;
  - the stop stays Next with one Navigate;
  - postponing the other moves it to Postponed;
  - the stop then leaves the sequence.
- **Reroute:** a grouped stop stays grouped after a reroute.
- **Isolation:** a group never exposes another rider's orders. If a group is split across riders, each rider sees only their own orders at the shared stop.

**Risks, defaults and decisions**
- **Identical pins can mean different buildings,** for example a campus-wide place link. Default: no automatic grouping, admin confirmation required (Q4-1).
- **Admin effort:** grouping is an extra admin step. It is optional; ungrouped identical pins still work, as separate stops at the same point.

### 4D: Integration and device verification

**User-visible behaviour**
- **Recalculate my route:**
  - **Placement:** a separate section, not inside the unchanged Route card.
  - **Entry points:**
    - after Postpone from the next-customer panel ("Keep current order" or "Recalculate my route"; nothing happens automatically);
    - when orders are "Not in your route";
    - after a confirmed destination change;
    - on demand.
- **Origin chooser:**
  - **Use my current location** asks for permission on the tap.
  - **On failure** it shows the reason (denied, unavailable, timeout, insecure connection, too inaccurate, outside the area, no road nearby) and the honest fallbacks:
    - "From your last completed stop: RW-… (not your current position)";
    - otherwise "From the Office/Warehouse (your configured start)".
  - Nothing is preselected or remembered.
- **Progress and results:**
  - "Recalculating, needs a connection". All status actions wait.
  - Success: "Route recalculated from ⟨origin⟩ at 14:05", with the new order.
  - Failure, stale or busy: a reason, with "Your previous route is still shown" and Retry.
  - Offline: the action is disabled with a connectivity message (R22). There is no local reordering.
- **Shared stops:** one stop container ("Stop 3 · 2 customers at this location") with one Navigate and per-customer cards.
- **Endpoint change:** "Your route still ends at ⟨previous destination⟩ until you recalculate", then Confirm, then Recalculate.
- **Admin plan view:** per rider, "Recalculated by rider at hh:mm from ⟨origin kind⟩", and effective distances. No positions.

**Schema / API / UI**
- **Schema / API:** none beyond 4B and 4C.
- **UI:**
  - the reroute section, origin chooser, run polling (bounded, cancelled on navigation like 2C), shared-stop rendering, endpoint-change prompts, and admin effective-route display;
  - `isSecureContext` and geolocation detection.
- **Script:** `scripts/phone-server.sh` gets a localhost / `adb reverse` mode (§2.9).

**Dependencies:** 4A, 4B, 4C; Q4-6 for the phone check.

**Acceptance tests**
- **Browser, mocked geolocation, recorded matrices, 1280 and 390 px:**
  - granted at `gps_r1`: the route is recalculated and the origin labelled;
  - denied: the fallback is offered and only used when chosen;
  - timeout or unavailable (stub): the same;
  - no completed stop: configured start, explicit;
  - offline: disabled;
  - a double tap gives one run;
  - status actions are disabled during a run;
  - shared-stop partial completion (A21);
  - endpoint change, then confirm, then recalculate, with rider B's screen unchanged (A20);
  - Postpone and reroute with rider B's view and the admin view showing B unchanged (A18);
  - an admin optimizing during a rider's run gives a correct stale or superseded message;
  - isolation: guessing another rider's run or round id fails;
  - no external navigation or dialling.
- **Live:** an opt-in browser reroute on the real local tiles (`ROUTEWISE_E2E_LIVE=1`).
- **Evidence:** screenshots in `docs/phase4/screenshots/4d/`; earlier evidence is never written. The words "mocked geolocation" appear in the evidence wherever they apply.
- **Phone checklist** (owner, recorded as owner-reported):
  - secure-context setup;
  - quick call and Postpone with the next customer updating;
  - location granted (inside DU coverage, or record the refusal if outside);
  - location denied, then the last-completed-stop fallback labelled;
  - no completed stop, then configured start;
  - shared stop partial completion;
  - endpoint change with only own recalculation;
  - shut down.

**Risks, defaults and decisions**
- **Device limits:** GPS indoors is often > 100 m accurate, so the fallback path will be common. Only one Android phone is available (no iPhone check).
- **Coverage:** a real GPS success needs the phone inside the tile coverage.

## 4. Decisions needed

Defaults are proposals, not approvals.

| # | Question | Proposed default | Needed by |
|---|---|---|---|
| Q4-1 | Do identical pins group automatically, or only after admin confirmation? | Only after admin confirmation; nearby pins never | 4C |
| Q4-2 | GPS acceptance thresholds | Accuracy ≤ 100 m, fix ≤ 60 s old, inside the service area | 4B |
| Q4-3 | With no GPS and no completed stop, may the rider enter a position (coordinates or Google Maps link, no map tiles)? | Not in Phase 4. The explicit configured start is the only option ([working flow §7](../source/notion/RouteWise/02-Working-Flow.md) allows "pin or configured start") | 4B |
| Q4-4 | Does a Pending first-priority order stay first when rerouting mid-round? | Yes (D05 applied to the remainder) | 4B |
| Q4-5 | Should an admin pin, priority or lock edit on one rider's order invalidate only that rider's route? | No in Phase 4: round-wide as today (conservative); revisit after use | 4B |
| Q4-6 | Real-phone secure context | `adb reverse` to `http://localhost:8020` over USB | 4D |
| Q4-7 | Does an admin round re-optimization supersede rider reroutes, and are rider reroutes refused while one runs? | Yes to both (§2.6) | 4B |
| Q1 | Whole-round re-optimization after issue (pending since Phase 2) | Unchanged and not built. Interacts with §2.6 | — |
| Q7 | Snap-distance guard (pending since Phase 2) | Unchanged; GPS origins use the existing unroutable checks | — |

**Used in 4B as provisional local defaults.** The owner's 4B instructions set these values for the implementation; they are configurable and not permanent product decisions:
- **Q4-2:** accuracy ≤ 100 m and fix age ≤ 60 s (`ROUTEWISE_REROUTE_GPS_MAX_ACCURACY_M`, `ROUTEWISE_REROUTE_GPS_MAX_AGE_S`), inside the service area.
- **Q4-3:** no manual position entry.
- **Q4-4:** the remaining first-priority order stays first.
- **Q4-5:** admin edits keep round-wide invalidation.
- **Q4-7:** new rider reroutes are refused while an admin optimization is active, and an admin plan supersedes rider revisions.

**Still pending:** Q4-1 and Q4-6.

## 5. Blockers and limits

- **Starting 4A:** none. It needs only plan approval.
- **Phone geolocation:**
  - The current phone server cannot provide a secure context, so a real-device GPS check needs Q4-6 (USB + `adb reverse` by default).
  - A *successful* real GPS reroute is possible only with the phone physically inside the local tile coverage (DU North Campus buffer). Elsewhere, only refusal and fallback can be checked on the device.
- **Data gaps:** orders Completed before migration 0005 have no completion time, so they can never be offered as the last completed stop.
- **Single device:** only one Android phone (OnePlus Nord 5, Chrome) has been used. iPhone/Safari remains untested.

## 6. Work order and evidence

1. **4A:** UI, unit and browser tests. Commit; owner review.
2. **4B:** migration 0005, reroute port with parity tests, rider runs, API, race and privacy tests, opt-in live test. Commit; owner review.
3. **4C:** migration 0006, grouping API, admin UI, planner and reroute grouping tests. Commit; owner review.
4. **4D:** rider screens, browser suite (mocked geolocation labelled), live opt-in run, phone checklist and results template, then the Phase 4 report.

**Gate** (roadmap): owner acceptance after the phone checks.
- only the rider's remaining sequence changes;
- completed orders and other riders' ownership and routes are preserved;
- denied location has an honest fallback;
- shared-stop orders keep independent statuses;
- postponed reinsertion works under D08.

**Evidence** goes to `docs/phase4/evidence/` and `docs/phase4/screenshots/{4a,4b,4c,4d}/`. Phase 1–3 evidence and `docs/source/` are never rewritten.
