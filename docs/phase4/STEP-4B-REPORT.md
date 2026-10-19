# Step 4B report: individual rerouting and endpoint-change recalculation

**Status:** 4B is **implemented, verified with automated tests and one real local-Valhalla check, committed (§8), and awaiting owner review**. Rerouting is **API-only until 4D**. Phase 4 is **incomplete**: 4C (shared stops) and 4D (rider screens, GPS capture, device checks) have not started.

| | |
|---|---|
| Date | 19 October 2026 |
| Prepared by | Claude Code |
| Baseline | `e40e0b0` (4A) |
| Plan | [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) §2 and §3 4B |
| Requirements | R17, R18, R19, R22, R23; D05, D06, D08, D11; tasks P4-02, P4-03; acceptance cases A18–A20 (API level) |

**Authorization:** the owner authorized **4B only**. Nothing was deployed, and Notion was not accessed.

**Provisional local defaults:** the owner's 4B instructions set these values for this implementation. They are **configurable, and not separately approved permanent product decisions**:

| Plan item | Default used in 4B | Where |
|---|---|---|
| Q4-2 | Device fix accuracy ≤ 100 m, age ≤ 60 s, inside the service area | `config.RerouteLimits`; `ROUTEWISE_REROUTE_GPS_MAX_ACCURACY_M`, `ROUTEWISE_REROUTE_GPS_MAX_AGE_S` |
| Q4-3 | No manual position entry | No endpoint accepts one |
| Q4-4 | A remaining first-priority order stays first | Solver constraint and invariant check |
| Q4-5 | Admin edits keep round-wide invalidation | Unchanged from 3B |
| Q4-7 | New rider reroutes are refused while an admin optimization is active; an admin plan supersedes rider revisions | `ROUND_REPLANNING`; `commit_plan` |

Q4-1 (grouping, 4C) and Q4-6 (phone secure context, 4D) remain pending.

## 1. What it does

**Who can change what:**
- A rider can recalculate the order of **their own remaining Pending orders**.
- Nothing else changes:
  - the admin's round plan (`route_plans` / `plan_routes` / `plan_orders`);
  - `assignments`;
  - every order;
  - Postponed ownership and Completed history;
  - every other rider's route and revisions.
- Tests compare all of these row by row, before and after.

**How the result is stored and read:**
- The result is a **rider route revision** layered on the current round plan.
- The rider's **effective route** is their current revision of the current plan, or else their plan route. The rider and admin views read it through one shared helper (`rider_routes.py`).

**Origins.** Each one is explicit and labelled, and the server never picks one for the rider:

| Origin | When it is allowed | Label shown |
|---|---|---|
| `current_position` | One fresh device fix with this request | "your current position (device location)" |
| `last_completed_stop` | The rider's own latest completion with a recorded time, from an order they marked Completed. The request must name the order the rider was shown; a newer one gives `ORIGIN_CHANGED` | "your last completed stop, not your current position" |
| `configured_start` | Only while the rider has no such completed stop (working flow §7) | "your configured start, not your current position" |

- **Device fix:** refused if less accurate than the limit, older than the limit, non-finite, invalid, or outside the DU North Campus service area. It is used once, in memory, and never stored, logged, echoed or reused.
- **No silent fallback:** a stored or old location is never substituted for a current position.

**Completion records:**
- Since 4B, any transition into Completed records `completed_at` and `completed_by`, by rider or admin. Leaving Completed clears both.
- Orders completed before the migration keep NULL ("time unknown"). They are **never offered** as the last completed stop; no timestamp is invented.
- An admin's completion is never the rider's location.

**Destination change (R23):**
- A rider's own destination change after planning:
  - resets their confirmation;
  - makes in-flight solves stale;
  - marks **only their route** `awaiting_recalculation: "destination_changed"`.
- **Other riders:** their routes stay current, and they are not asked to reconfirm. The round plan is not out of date.
- **After the rider confirms:** a reroute ends at the new destination (`trigger: "endpoint_change"`).
- **Confirmation itself** no longer invalidates the round.

**Routing details:**
- **Vehicle profile:** from the rider's current round setup (scooter → `motor_scooter`, bike → `motorcycle`).
- **Priority:** a remaining first-priority Pending order stays first. Two would be refused with `PRIORITY_CONFLICT`.
- **Capacity:** held + Pending must fit the capacity; ownership never moves.
- **Last stop:** the route stays **open**, and its distance excludes the virtual final arc.
- **Road data:** distances are real road only; a recorded or synthetic matrix is never saved from.

**Reinsertion (D08):** a Postponed order returned to Pending outside the effective sequence shows as not in the route. The rider's next reroute includes it. Nothing returns automatically.

**Admin replanning:**
- A new round plan **supersedes** every rider revision of the plan it replaces. The revisions are kept as history and marked superseded, and the plan summary lists `rider_revisions_superseded`.
- A reroute in flight when the admin's plan commits ends `stale` (`ROUND_REPLANNED`).
- New reroute requests are refused while an admin run is active.
- Admin runs are never blocked by rider runs.

**Connectivity (R22):** a reroute is a server action with no offline path.

**Route summary card:** unchanged. The rider page renders nothing new: reroute screens and device-position capture are 4D. The cards and the 4A panel follow the effective sequence automatically.

## 2. Schema (migration `0005_phase4b_rider_routes`)

| Change | Purpose |
|---|---|
| `round_riders.route_version` | Rider-scoped route validity |
| `plan_routes.rider_route_version` | The rider's `route_version` when the round plan was committed |
| `orders.completed_at`, `orders.completed_by` (→ users, SET NULL) | Completion record. CHECK: both or neither; only while Completed |
| `planning_runs.scope` (`round`/`rider`), `rider_id`, `base_plan_id`, `origin_kind` | Rider runs share the bounded worker, recovery and expiry. The single active-run index becomes `uq_planning_runs_one_active_round` (one per round) and `uq_planning_runs_one_active_rider` (one per rider and round) |
| `route_revisions` | One row per rider recalculation. FK (`plan_id`, `rider_id`) → `plan_routes`; one current per plan and rider; trigger; origin kind (plus `origin_order_id` for the fallback only); vehicle and profile (CHECK pairing); endpoint kind and `open_route` (CHECK); real-road distances; rider and round route versions; keyed fingerprint; provenance without coordinates |
| `revision_orders` | The revision's active Pending sequence (`stop_seq`) |

**No column stores a device position.** Upgrade, downgrade and upgrade were run, and the schema matches the models (`test_migrations_privacy`).

## 3. API

**Rider:**
- **`POST /api/rider/rounds/{round_id}/reroute`:**
  - Body: `{"origin": {...}, "expected_plan_version": n, "expected_revision": n}`.
  - Returns 202 and a run, or one of these coded refusals:
    - `404`: not the rider's round;
    - `409`: `NO_PLAN`, `NOT_IN_PLAN`, `ROUND_OUT_OF_DATE`, `NOT_CONFIRMED`, `ROUND_REPLANNING`, `REROUTE_IN_PROGRESS` (with the run id), `ROUTE_CHANGED`, `ORIGIN_CHANGED`, `COMPLETED_STOP_AVAILABLE`, `ACCOUNT_INACTIVE`;
    - `422`: `POSITION_UNUSABLE`, `ORIGIN_INVALID`, `NO_COMPLETED_STOP`, `NOTHING_TO_REROUTE`, `PRIORITY_CONFLICT`, `HELD_ORDERS_EXCEED_CAPACITY`;
    - `503`: `PLANNING_BUSY`, `ROUTING_ENGINE_UNAVAILABLE`.
  - CSRF and Origin are enforced, as for every rider mutation.
- **`GET /api/rider/reroutes/{run_id}`:**
  - **Visible to:** the requesting rider only; anyone else gets the same 404 as a missing run.
  - **Returns:** state, origin kind, error (code, message) and revision number.
  - **Failure codes:** `ROUTING_ENGINE_UNAVAILABLE`, `UNROUTABLE_ORIGIN`, `UNROUTABLE_ENDPOINT`, `INTERNAL`.
  - **Stale codes:** `INPUTS_CHANGED`, `ROUND_REPLANNED`.
- **`GET /api/rider/rounds/{id}/deliveries`:**
  - `sequence` follows the effective route.
  - `plan.route` is unchanged: the admin plan's route.
  - New `plan.rider_route`: revision (number, trigger, origin kind, origin order code, time), origin label, vehicle, destination, open route, distances, `awaiting_recalculation`.
  - New `reroute`:
    - `available`, `blocked` (code and message) and `in_progress_run_id`;
    - `last_completed_stop` (order id, code, customer, label) and `configured_start_allowed`;
    - `gps_limits`.
- **`PUT …/destination` and `POST …/confirm`:** use the new version rules (§4).
- **`POST /api/rider/orders/{id}/status`:** also records completion.

**Admin:**
- **`GET /api/admin/rounds/{id}/plan`:**
  - Each route gains `rider_route`: the revision, its stops by order code, distances and `awaiting_recalculation`.
  - `unplanned_pending` is computed against effective routes.
  - `summary.rider_revisions_superseded` lists rider names.
- **`POST …/optimize`:** ignores rider runs.
- **`GET …/planning-runs`:** lists round runs only.
- **`PATCH /api/admin/orders/{id}`:** maintains the completion record.

**Web:**
- Types for the new fields (`api.ts`).
- The admin plan page (`PlanView.tsx`) shows two one-line notes per rider:
  - "⟨Rider⟩ changed their destination after this plan. Only their route awaits recalculation…";
  - "Recalculated by the rider at … from their ⟨origin kind⟩: N stops, X km. The stops below are the saved plan."

  Without the first note, a rider's destination change would have removed the admin's only visual signal.
- No rider-page rendering changed.

## 4. Versions and locking

| Change | Round `input_version` | Round `route_version` | Rider `route_version` |
|---|---|---|---|
| Rider marks Completed / Postponed / returns to Pending | +1 | — | — |
| **Rider changes own destination** | +1 | — *(was +1)* | **+1** |
| **Rider confirms own setup** | +1 | — *(was +1)* | — |
| Admin: participation, vehicle, capacity, start; depot coordinates; account deactivation | +1 | +1 | — |
| Admin order edits (pin, status, lock, priority) | +1 | +1 | — |
| Rider reroute commit | — | — | — (recorded on the revision) |
| Admin round plan commit | — | — | — (recorded on each plan route) |

**Validity at read time:**
- **Round out of date:** `plan.route_version` ≠ round `route_version` (3B, unchanged).
- **Awaiting recalculation:** the effective route's `rider_route_version` ≠ the rider's current value.
- The 3B rule is kept: a status change bumps `input_version` only.

**Locks:**
- A reroute request and its commit take **depots FOR SHARE → round FOR UPDATE → the rider's own `round_riders` row FOR UPDATE** (then the run row). This is the documented 2A/2B order, so there is no new wait cycle.
- The commit never locks order rows. Inserting `revision_orders` takes KEY SHARE through the foreign keys, which does not conflict with the FOR NO KEY UPDATE of order edits.
- The rider's user row is read FOR SHARE, so a deactivation waits.
- Read-only views take no locks.

**Commit checks:** the revision is saved only if, under these locks:
- the base plan is still current (else `ROUND_REPLANNED`);
- the **rider-scoped keyed fingerprint** is unchanged (else `INPUTS_CHANGED`).

**The fingerprint covers:**
- the base plan and revision number;
- the round and rider route versions;
- account, participation, confirmation and configuration (vehicle, capacity, start, destination with Home/Custom coordinates, and the depot coordinates the rider uses);
- every order the rider owns: status, pin, location state, lock, priority and completion record.

**It deliberately excludes:**
- the round's `input_version`, so other riders' progress never stales this run;
- order versions and customer text.

**Then, in one transaction:**
- supersede the rider's previous revision for the plan;
- insert the new revision and its orders;
- re-read independently: the sequence is exactly the rider's own Pending orders;
- check that the round's `assignments` are identical before and after (else roll back, and the run is `failed`).

**Bounded work:**
- Rider runs use the existing worker and slots (503 when full).
- One active rider run per rider and round is enforced in code and by a partial unique index.
- A restart marks unfinished rider runs `interrupted`, and they never save.

## 5. Changed files

| File | Change |
|---|---|
| `services/api/migrations/versions/0005_phase4b_rider_routes.py` (new) | Schema above |
| `services/api/routewise_api/routing/reroute.py` (new) | Rider-only re-solve, ported from the accepted spike `reroute.py` onto the app planner primitives: one vehicle from an explicit origin to the confirmed endpoint or open route; unroutable origin/endpoint checks; invariant check |
| `services/api/routewise_api/reroute.py` (new) | Rider-scoped snapshot and fingerprint, origin rules, prechecks, solve, guarded commit, worker body, options view |
| `services/api/routewise_api/rider_routes.py` (new) | Effective route, `awaiting_recalculation`, revision view |
| `routewise_api/models.py`, `config.py` (`RerouteLimits`), `riders.py` (`bump_own_destination`), `orders.py` (`set_status`), `planning.py` (rider route version on plan routes, superseding revisions, rider jobs in the worker), `routers/rider.py`, `routers/admin.py`, `routers/admin_planning.py` | As described in §1–§4 |
| `services/api/tests/test_reroute.py` (new) | 32 tests |
| `tests/test_planning_live.py` | Opt-in live reroute test |
| `tests/conftest.py`, `tests/test_migrations_privacy.py` | New tables, head `0005` |
| `tests/test_rider_status.py`, `tests/test_rider_deliveries.py`, `tests/test_planning_concurrency.py` | Updated to the **intended** R23 rule; see below |
| `services/api/tools/mutation_check.py` | 18 targeted 4B defects; optional `MUTATION_TESTS` selection |
| `apps/web/src/api.ts`, `apps/web/src/components/PlanView.tsx`, `apps/web/src/next.test.ts` | Types, admin notes, test fixture fields |
| `apps/web/e2e/phase4b.spec.ts` (new), `apps/web/e2e/phase2.spec.ts` | 4B browser check; the Phase 2 stale-run test now asserts the R23 outcome |
| `services/api/scripts/phone_db.py` (new), `scripts/phone-server.sh`, `services/api/tests/test_phone_db.py` (new, 8 tests) | Phone-database schema preflight and explicit upgrade (§9) |
| `docs/phase3/PHONE-TEST-GUIDE.md` | New section A0: bring an existing `routewise_phone` up to date, keeping its data |
| `docs/phase4/IMPLEMENTATION-PLAN.md`, `docs/DEVELOPMENT.md`, `CLAUDE.md`, `README.md`, `docs/README.md` | Status, provisional defaults, API notes, schema check |

**Existing tests changed because the contract intentionally changed (R23),** not to make failures pass:
- **`test_rider_status`:**
  - `_destination` was removed from the "genuine changes mark the plan out of date" list;
  - a new test asserts the input version moves, the round route version does not, only Rider C awaits recalculation, and nobody else must reconfirm.
- **`test_rider_deliveries`:** the own-destination-change test now expects "awaiting recalculation" for that rider instead of a round-wide "out of date".
- **`test_planning_concurrency`:** both commit-race tests keep their serialisation assertions. The "invalidated" check is round-wide for admin and configuration edits, and rider-only for the rider's destination change.
- **`phase2.spec.ts`:**
  - **Still asserted unchanged:** the stale-run and nothing-saved assertions.
  - **Changed:** the plan page no longer shows the round-wide "out of date" banner. It shows Chitra's "awaiting recalculation" note, and none for Asha.

## 6. Verification (actual results, 19 October 2026)

| Check | Result | Evidence |
|---|---|---|
| API suite (PostgreSQL, **recorded** real-road matrices, **mocked** device positions) | **387 passed, 2 skipped** (the opt-in live tests) before review; **395 passed, 2 skipped** after the review additions (the 8 phone-database tests; no other test changed) | `evidence/step4b_api_pytest.txt` |
| New 4B API tests | 32 (in the 387) | `tests/test_reroute.py` |
| Real local Valhalla (opt-in) | **2 passed**: the existing live plan, and the new live reroute | `evidence/step4b_api_live_valhalla.txt` |
| Targeted backend defects | **17/18 killed** in the full 18-defect run. The one survivor was a test gap; after coverage was added, a rerun of **that single defect** killed it (1/1). The full set was **not** rerun | `evidence/step4b_api_mutation_checks.txt` |
| Web typecheck / unit tests / build | OK / **23 passed** / OK | `evidence/step4b_web_checks.txt` |
| Browser suite (1280 + 390 px, recorded matrices) | **64 passed, 2 skipped** (the opt-in live Phase 2 spec) | `evidence/step4b_e2e_playwright.txt` |
| Phone-database schema preflight and upgrade (§9) | 8 new tests; launcher run against the real `routewise_phone` (still on 0004) stopped before building or serving; upgrade of a **copy** of it kept all 15 existing tables' rows | `evidence/step4b_phone_db_upgrade_check.txt` |
| Routing regression (Phase 0 spike suite) | **Not rerun locally** (spike code unchanged); CI runs it on push | — |

**Live reroute check:**
- **Real:** the road matrix and the solve use the real local Valhalla tiles.
- **Mocked:** the "device position" is the public fixture point `gps_r1`, typed into the test's request. It is not a reading from any device.
- **Run:** Rider A reroutes four Pending stops from that point.
- **Provenance:** `valhalla-local (OpenStreetMap data)`, real road, not recorded, profile `motor_scooter`, solver status `SUCCESS`.
- **Distances:** 7,068 m. Distance and duration equal the directed recorded costs along the same path.
- **Timings:** matrix 0.017 s, solve 0.078 s, total 0.096 s (6 points). The 10 s `solve_seconds` is a ceiling only.

**Defect check survivor:** the one survivor ("own status not part of the rider input") was a **test gap**. The race test completed an order, which also changes the completion record, which is in the fingerprint. A Postpone variant (status only) was added. Rerunning **only that defect** then killed it (1/1). The other 17 were killed in the first run and the full 18 were **not** run a second time, so this is 17/18 plus one targeted rerun, not a second complete 18-defect run.

**Routing regression:** the spike code is unchanged. The application's routing parity tests (`test_routing_parity.py`) ran inside the API suite. CI runs the spike suite on push.

**Test data:** the suite plans with **recorded** real-road matrices through a test-only seam, and every device position in it is a **mock** (a fixture coordinate in the request). Only the opt-in live check above uses real routing, and its position is also a mock. No test or check used a phone, a browser geolocation call or real GPS.

**Browser screenshots:** 4 new synthetic screenshots in `docs/phase4/screenshots/4b/` (rider after a revision; admin note), at 1280 and 390 px. The admin note was inspected and is readable. Phase 1–4A screenshots were not written: their output went to scratch.

**The 4B API tests prove:**
- **Isolation:** only the rider's own sequence changes. Other riders' rows, all plan rows, assignments, orders, round riders and endpoints are byte-identical. Other riders' views are unchanged. Postponed and Completed keep their owner.
- **Distances:** equal the recorded directed costs from the origin (device position, configured start or last completed stop) to Home, Warehouse or Custom, or open for Last stop.
- **Privacy:** the device position appears in **no table, log, response or admin view** (full database text dump plus captured logs).
- **Origins:**
  - no completed stop gives `NO_COMPLETED_STOP`, and configured start succeeds only when asked;
  - after a completion, configured start is refused (`COMPLETED_STOP_AVAILABLE`);
  - a stale or another rider's order is `ORIGIN_CHANGED`;
  - the latest completion works and supersedes revision 1 with revision 2;
  - NULL completion times are never offered, and an admin completion is never offered;
  - reopening clears the record.
- **Position checks:** inaccurate, old, outside the area, incomplete, non-finite, and coordinates on the wrong origin are each refused, with nothing echoed and no run created. The limits are configurable by environment.
- **A20:** after Home → Warehouse, only that rider awaits recalculation and others need no reconfirmation. The reroute is refused until confirmed, then ends at the Warehouse with `endpoint_change`. A later admin plan supersedes the revision.
- **Reinsertion:** a returned Postponed order is unsequenced until the next reroute includes it, and the admin's `unplanned_pending` follows.
- **Routing details:** priority stays first, Last stop stays open, and each vehicle uses its own profile (`motorcycle` / `motor_scooter`).
- **Failures:**
  - a provider failure, or an unroutable origin, ends with the run `failed`, and the effective route is unchanged;
  - one run per rider at a time (409 with the run id);
  - runs are private (another rider gets 404);
  - an interrupted run never saves.
- **Races during the solve:**
  - **Stale (`INPUTS_CHANGED`):** own Completed, own Postponed, own destination, admin pin, admin status, capacity, ownership/lock change, account deactivation.
  - **Not stale:** another rider's progress, or another rider's reroute committing meanwhile.
  - **Admin plan commits first:** `ROUND_REPLANNED`.
  - **Admin run active:** new requests refused with `ROUND_REPLANNING`.
- **Final commit race:** own status, another rider's status, or an admin pin edit waits on the round lock and lands after the revision. Progress leaves routes valid; the admin pin makes the round out of date.

## 7. Limitations

- **No rider reroute screens or device-position capture** (4D). Reroutes are requested through the API. Until 4D:
  - the rider's route summary card still shows the admin plan's totals, and its "planned from … to …" note compares with the plan's destination;
  - the rider sees no "awaiting recalculation" prompt. The setup card shows "confirm again", and the existing note shows the plan's old destination.
- **Device position is unverifiable server-side:** the server cannot prove a fix is fresh. It trusts the device's reported accuracy and age, checks them against the provisional limits, labels the origin, and stores nothing.
- **Coverage:** a position outside the DU North Campus service area, or with no road nearby, is refused or fails. No snap-distance guard exists yet (Q7 pending).
- **Conservative staleness (Q4-5 default):** an unrelated admin edit makes the round out of date and blocks every rider's reroute until the admin re-optimizes.
- **Admin replanning mid-round** still plans from configured starts and may move Pending orders between riders (Q1 pending). It supersedes rider revisions.
- **No shared stops yet (4C).** Grouping code is reused unchanged and forms no groups, because no order has a building id.
- **Historical completions:** orders completed before migration 0005 have no completion time and are never a fallback origin.
- **Phone GPS has not been tested.** No browser geolocation code exists yet (4D), no device was used, and every origin in tests is a fixture point (the "device position" is mocked).
- **Not done:** no retention purge, offline queue (Phase 5) or live refresh.

## 8. Git state

- **Baseline:** `main` at `e40e0b0` (4A), in sync with `origin/main` when 4B started.
- **Committed:** every file in §5, the 4B evidence (`docs/phase4/evidence/step4b_*`), `docs/phase4/screenshots/4b/` and this report, as one commit, "Add RouteWise individual rider rerouting", pushed to `origin/main` without force. (A commit cannot contain its own hash; it is in the hand-off message and `git log`.)
- **Not committed, by design:** databases, tiles, environments, caches, `.env`, and `.local/` (including the local phone-test credentials and expected stops).
- **Not done:** nothing deployed; Notion not accessed; the separate stable preview was not touched; `routewise_phone` was **not** upgraded (the owner does that, §9). 4C and 4D have not been started.

## 9. Phone-test startup: schema preflight

**What went wrong before:** the phone database was still on migration 0004 while the new code expected 0005, so sign-in and the rounds screen failed with `column round_riders.route_version does not exist`, and nothing said why.

**What is there now** (`services/api/scripts/phone_db.py`, called by `scripts/phone-server.sh` before it builds or serves):
- `check` (read-only; the transaction is `READ ONLY`) compares the database's revision with the code's. If it differs it prints what to do and the launcher stops with "The server was not started."
- States handled: current, outdated (a known older revision), uninitialised, unknown revision (newer code built it), and unreachable or missing. The connection details are never echoed.
- **Nothing is reset, rebuilt or migrated by the launcher.** Upgrading is the separate, explicit command `phone_db.py upgrade`, run by the owner. It touches only `routewise_phone` (it refuses any other name), only when the database is at a known older revision, and keeps the existing rows (the migrations add; they do not drop). A failed migration step rolls back (PostgreSQL DDL is transactional).
- `phone_setup.py` is unchanged and remains the data-deleting rebuild, named as an alternative only.

**Owner steps** (guide section A0): stop the phone server, `phone_db.py check`, then `phone_db.py upgrade`, then `scripts/phone-server.sh`.

**Checked** (`evidence/step4b_phone_db_upgrade_check.txt`):
- The launcher, run against the real `routewise_phone` (still on 0004), printed the instructions, exited 1 and left nothing listening.
- An upgrade of a **copy** of that database kept all 15 existing tables' row counts and defaulted `route_version` to 1.
- Orders Completed before the upgrade have no completion time (never a fallback origin).
- Eight repeatable tests run on the test database.
