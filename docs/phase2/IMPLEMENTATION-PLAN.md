# Phase 2 implementation plan — routing and multi-rider constraints

**Date:** 17 October 2026 · **Prepared by:** Claude Code · **Status: step 2A committed (`13de782`); step 2B committed locally, awaiting review** ([2A report](STEP-2A-REPORT.md), [2B report](STEP-2B-REPORT.md)). Step 2C has not started. Phase 2 is not complete.

**Baseline:** Phase 1 accepted for local development on 13 October 2026 at `fcac55e` ([record](../phase1/OWNER-ACCEPTANCE-2026-10-13.md)); Phase 0 accepted at `2a34226` ([record](../phase0/OWNER-ACCEPTANCE-2026-10-13.md)) with decisions D04–D10. Scope: [01-Product](../source/notion/RouteWise/01-Product.md) R07–R13 and R19, roadmap [Phase 2](../source/notion/RouteWise/04-Roadmap.md), tasks P2-01…P2-05, acceptance cases A12–A14.

**Constraints carried into every step:** DU North Campus, Delhi; ₹0; local self-hosted Valhalla on OpenStreetMap only (Google/Stadia stay inactive; no public demo servers); no deployment, no GitHub push, no Notion access. No compulsory package or dispatch confirmation, no fuel analytics, no postponed dashboard, no balanced-workload mode. Statuses stay exactly Pending / Postponed / Completed. Endpoint confirmation is required and is not dispatch confirmation.

## 1. Starting point (what exists today)

**Accepted spike (`spikes/routing/routewise_spike/`, frozen evidence):**

| Module | What it already proves | Reuse in Phase 2 |
|---|---|---|
| `models.py` | Domain types: `StartKind` (office/warehouse), `EndpointKind` (office/warehouse/home/last_stop/custom), `Vehicle` (scooter/bike), `DistributionMode`, `Plan`, `RiderRoute`, `Stop` | Port as the planner's in-memory domain |
| `gate.py` | `endpoint_gate_issues`: every *active* rider needs a confirmed, valid endpoint; issues name rider + reason only | Port unchanged |
| `planner.py` | OR-Tools model: per-rider start/end, Last stop as zero-cost virtual sink excluded from reported distance, order-count capacity (D06), locks, equal band (D07), priority-first (D05), missing edges removed from the successor domain (never 0), coded infeasibility, `validate_plan`, fingerprint, `PlanStore` stale rejection, per-profile matrices for mixed fleets | Port; replace `PlanStore` with a PostgreSQL commit |
| `matrix/base.py`, `recorded.py`, `valhalla_local.py` | Provider-neutral directed matrix with provenance (`real_road`, `recorded`), `NO_ROUTE`/`ERROR` never priced, in-process Valhalla `Actor`, `motor_scooter` and `motorcycle` only | Port; Google/Stadia/OSRM/synthetic adapters are **not** ported (inactive or test-only) |
| `reroute.py`, building grouping | Phase 4 behaviour | **Not ported.** The spike tests stay and keep running |

Supporting evidence reused: `tests/fixtures/public_locations_du_north.json` (17 public OSM points), `tests/fixtures/recorded/valhalla_du_north_{motor_scooter,motorcycle}.json` (recorded real local-Valhalla matrices), `spikes/valhalla/build_tiles.sh` (local tiles, git-ignored), solver benchmark (~1 s / 20 orders, ~5–6 s / 50, ~12–14 s / 100 on a synthetic matrix).

**Application (`services/api`, `apps/web`):** `riders` (user link, display name, optional vehicle), `delivery_rounds` (one per committed import), `orders` (resolved pin or `needs_correction`, `building_id` unused, `version`), `assignments` (PK `order_id` → exactly one rider), `orders.planning_input()` as the only path to an optimizer (resolved pins inside the service-area box), `GET /api/admin/rounds/{id}/readiness`, `require_admin`/`require_rider`, CSRF on every mutation, route-inventory permission test, `tools/mutation_check.py`. The API venv has neither OR-Tools nor pyvalhalla yet.

**Approach to reuse:** copy the needed spike modules into `services/api/routewise_api/routing/` with a header naming the source commit, keep the spike byte-for-byte unchanged, and add a parity test proving the port gives the same results as the spike on the recorded DU matrices. The spike stays the accepted reference; the API owns production code.

## 2. Step overview

| Step | Delivers | Depends on | Roadmap tasks |
|---|---|---|---|
| **2A** | Office/Warehouse locations, rider management, per-round participation/vehicle/capacity/start, each rider's own endpoint selection + confirmation, gate status | Phase 1 (accepted) | P2-01, P2-02 (API) |
| **2B** | Ported OR-Tools planner on local Valhalla, equal/smart/manual, capacities, priority, locks, rider-specific endpoints incl. open Last-stop route, infeasibility handling, background planning run, versioned persisted plans, stale-plan rejection | 2A | P2-02 (gate in planner), P2-03, P2-04 |
| **2C** | Admin planning screens, minimal rider destination card, browser end-to-end tests, real-road integration run, Phase 2 report | 2B | P2-05 |

Each step ends with the full regression run (section 6) and a short evidence note in `docs/phase2/evidence/`. A step is not started until the owner asks for it.

---

## 3. Step 2A — riders, vehicles, capacities, starts and rider-confirmed destinations

> **Implemented 17 October 2026, awaiting review.** The [step 2A report](STEP-2A-REPORT.md) records what was built and where it differs from this section. In short: the rider confirms the whole round setup (`round_riders.config_version`), not only the destination. Endpoint status is part of `GET /api/admin/rounds/{id}/riders`, not a separate endpoint. Home/Custom accept coordinates only, with no Maps link yet. Rider routes use `/destination` and `/confirm`.

### Behaviour

1. **Office and Warehouse.** Admin sets one Office and one Warehouse location (label + coordinates, optional Google Maps link resolved through the Phase 1 resolver; `netsafe.py` for short links). Both must lie inside the DU North Campus service area. A change bumps a version and invalidates any round fingerprint that uses it (2B).
2. **Rider management.** Admin lists rider accounts and edits display name and default vehicle (`scooter` or `bike` = motorbike). Account creation, password reset and deactivation stay in the Phase 1 CLI (see decision Q5). Deactivated users cannot participate.
3. **Per-round configuration.** For each round the admin chooses participating riders and, per rider: vehicle (defaults from the profile), capacity in orders (integer ≥ 1, D06) and start (Office or Warehouse). Removing a rider from a round sets `participating = false`; that rider no longer counts toward the confirmation gate (architecture contract step 1).
4. **Rider destination, chosen by the rider.** A participating rider (own session only) selects one of Office, Warehouse, Home, Last stop, Custom for that round. Home and Custom need a resolved location (coordinates, or a Maps link resolved by the Phase 1 resolver) inside the service area; Last stop carries no location (open route). Saving clears any earlier confirmation. A separate **confirm** call, sent with the version the rider was shown, records `confirmed_at`. Any later change to kind or location resets the confirmation. The admin cannot select or confirm on a rider's behalf (Q4).
5. **Gate status.** Admin sees, per participating rider: endpoint kind, *confirmed / not confirmed / missing / location invalid*, never Home/Custom coordinates (R24, Q3). The existing readiness endpoint is extended to report order blockers, depot blockers, rider-configuration blockers and endpoint-gate blockers together.
6. **Isolation.** A rider can read and change only their own endpoint for rounds they participate in; anything else returns the same 404 as a missing record. No endpoint coordinates appear in logs, error messages or admin responses.

### Schema (migration `0002_phase2a_riders_endpoints.py`)

| Table | Columns and constraints |
|---|---|
| `depots` (new) | `kind` PK CHECK IN ('office','warehouse'); `label`; `lat`, `lng` NOT NULL with range CHECKs; `location_source`; `version`; `updated_by` → users; `updated_at` |
| `round_riders` (new) | PK (`round_id` → delivery_rounds CASCADE, `rider_id` → riders RESTRICT); `participating` bool; `vehicle` CHECK IN ('scooter','bike') NOT NULL; `capacity` int CHECK > 0; `start_kind` CHECK IN ('office','warehouse'); `version`; timestamps |
| `rider_endpoints` (new; kept apart from `round_riders` so private coordinates are isolated and easy to purge under D10) | PK (`round_id`, `rider_id`) → round_riders CASCADE; `kind` CHECK IN ('office','warehouse','home','last_stop','custom'); `lat`, `lng` nullable with range CHECKs; CHECK `(kind IN ('home','custom')) = (lat IS NOT NULL AND lng IS NOT NULL)`; `location_source`; `version`; `confirmed_at` nullable; CHECK `confirmed_at IS NULL OR confirmed_version = version` (confirmation belongs to one exact version); `updated_at` |
| `delivery_rounds` (changed) | `input_version` int NOT NULL DEFAULT 1, incremented in the same transaction by every change that affects planning input (used by 2B stale detection) |

### Files

- New: `routewise_api/riders.py` (round-rider and endpoint rules), `routewise_api/routers/admin_riders.py` (or a section of `routers/admin.py`, matching existing style), endpoint routes in `routers/rider.py`, `migrations/versions/0002_…py`, `tests/test_riders_endpoints.py`.
- Changed: `models.py`, `orders.py` (readiness aggregates new blockers), `routers/admin.py` (readiness), `tests/test_permissions.py` (route inventory + role/CSRF/isolation for every new endpoint), `tests/test_migrations_privacy.py` (round-trip, no-diff, no endpoint coordinates in logs), `tools/mutation_check.py`, `scripts/e2e_setup.py` (seed riders), `docs/DEVELOPMENT.md`.

### API (all under existing auth; every mutation needs CSRF and an expected version)

| Method and path | Role | Purpose |
|---|---|---|
| `GET /api/admin/depots`, `PUT /api/admin/depots/{kind}` | admin | Office/Warehouse |
| `GET /api/admin/riders`, `PATCH /api/admin/riders/{id}` | admin | Rider profiles (name, default vehicle) |
| `GET /api/admin/rounds/{id}/riders`, `PUT /api/admin/rounds/{id}/riders/{rider_id}` | admin | Participation, vehicle, capacity, start |
| `GET /api/admin/rounds/{id}/endpoint-status` | admin | Kind + gate reason per rider, no coordinates |
| `GET /api/rider/rounds` | rider | Rounds I participate in |
| `GET /api/rider/rounds/{id}/endpoint`, `PUT …/endpoint` | rider | Read / select my destination |
| `POST /api/rider/rounds/{id}/endpoint/confirm` | rider | Confirm exactly the version shown |

### Acceptance criteria

- Per-round scooter/bike, capacity and Office/Warehouse start are saved and versioned (P2-01).
- All five endpoint options can be saved and confirmed by the rider; Home/Custom without a valid in-area location and Last stop with a location are rejected by API and DB (P2-02).
- Changing a saved endpoint clears its confirmation; confirming a stale version returns 409.
- Removing a rider from a round removes them from the gate; re-adding requires a fresh confirmation only if their endpoint changed.
- Readiness lists every blocker by order code or rider display name, never coordinates.
- A rider cannot read or change another rider's endpoint (404), an admin cannot write any endpoint (403), anonymous gets 401, every mutation without CSRF gets 403.

### Meaningful tests

- DB: CHECK constraints reject capacity 0, unknown vehicle/start/kind, Home without coordinates, Last stop with coordinates, a confirmation that does not match the current version.
- API: each of the five kinds saved + confirmed; confirm-then-change resets; stale confirm → 409; out-of-area Home → 422; Maps-link Home resolved through the mocked resolver (network mocked, as in Phase 1).
- Gate: one participating rider unconfirmed → readiness blocked naming that rider; same rider removed from the round → not blocked.
- Permissions: route inventory updated; cross-rider 404; admin→rider-endpoint 403; CSRF matrix on every new mutation.
- Privacy: Home coordinates never in logs, admin responses, readiness or error bodies (captured-log test, as in Phase 1).
- Concurrency: two admins edit one round rider → one 409; `input_version` increments exactly once per accepted change.
- Mutation check: injected "gate ignores unconfirmed", "admin can confirm", "coordinates in status response" are caught.

---

## 4. Step 2B — local Valhalla + OR-Tools planning, persisted versioned plans

> **Implemented 17 October 2026, awaiting review.** The [step 2B report](STEP-2B-REPORT.md) records what was built and where it differs from this section:
> - Plan orders live in one `plan_orders` table (role `active`/`postponed`/`completed`, with the stop position), rather than separate `plan_stops`/`plan_stop_orders` tables.
> - Run states include `interrupted`.
> - Recorded matrices are test-only.
> - No snap-distance guard is enforced: Q7 is still pending, and its limits are reported.
> - The size limits were set from local measurements: 80 orders, 8 riders and 100 road points per run.
> - Module layout: the files list below names `engine.py`, `adapter.py`, `runs.py` and `matrix/recorded.py`. The work is instead in `planning.py` (snapshot, prechecks, worker, commit, recovery) and `routers/admin_planning.py`. The routing package was ported from the spike at `2a34226`, and the recorded matrices are a test helper (`tests/recorded_matrix.py`).
> - Correction pass, 18 October 2026: account deactivation is a shared operation (`accounts.deactivate_user`, used by the CLI). It advances `input_version` of the rider's rounds, so their saved plans show out of date, and it serialises with plan commits. Order edits lock their order rows before the round row (`FOR NO KEY UPDATE`), not only the round row as item 10 says. The commit's explicit round lock is what serialises edits with its final check; this is now covered by a commit-point race test.

### Behaviour

1. **Inputs.** A planning run reads, in one consistent transaction: orders through `orders.planning_input()` (still the only path), participating round riders, confirmed endpoints, depots, locks, priorities and the round's mode. It records `input_version` and a content fingerprint (spike `fingerprint`, extended with endpoint and order versions).
2. **Gate first, synchronously.** `POST /optimize` runs the full precheck before queuing anything: endpoint gate (409 `ENDPOINTS_NOT_CONFIRMED` with rider names and reasons), unresolved/out-of-area pins, missing depots, incomplete rider configuration, invalid locks, manual mode without an owner for every order, capacity and priority conflicts. So the API blocks exactly what the UI disables.
3. **Real directed road matrices.** One matrix per distinct profile present: scooter → `motor_scooter`, bike → `motorcycle` (beta upstream; accepted limitation). Never bicycle, auto, car or straight-line. The matrix covers stops, both starts and every fixed endpoint. A `NO_ROUTE`/`ERROR` element is a forbidden arc, never 0. Provenance (`provider`, `real_road`, `recorded`, profile, OSM data date, attribution) is stored with the plan.
4. **Unroutable locations.** A stop with no road in or out for the riders' profiles → `UNROUTABLE_LOCATION` with order codes. New in the port: the same check for depots and Home/Custom endpoints → `UNROUTABLE_ENDPOINT` naming the rider (not coordinates). Proposed snap-distance guard: before solving, Valhalla `locate` each new location and refuse pins further than a threshold from a routable edge (Q7), because a pin snapped far from its road would otherwise travel an unaccounted leg.
5. **Modes (D07).** *Smart:* minimise total road distance. *Equal:* near-equal order counts within capacity (water-filling band); an unmet band is a visible warning, not a silent change. *Manual:* every order needs an admin owner; only the sequence is optimised. Locks are honoured in all three modes.
6. **Starts and endpoints.** Each rider starts at the configured Office/Warehouse and ends at their confirmed endpoint. Last stop is an open route via the spike's zero-cost virtual sink; that arc is never included in reported distance or duration.
7. **First-delivery priority (D05).** Admin flags orders as first priority. A flagged stop can only follow a route start. Two flagged orders locked to one rider, or more flagged orders than riders, give `PRIORITY_CONFLICT` before solving.
8. **No silent drops.** Every eligible (Pending) order is planned exactly once. Coded failures: `INSUFFICIENT_CAPACITY`, `LOCK_EXCEEDS_CAPACITY`, `INVALID_LOCK`, `MANUAL_ASSIGNMENT_MISSING`, `PRIORITY_CONFLICT`, `UNROUTABLE_LOCATION`, `UNROUTABLE_ENDPOINT`, `NO_FEASIBLE_PLAN`, `ROUND_TOO_LARGE`, `ROUTING_ENGINE_UNAVAILABLE`, `INPUTS_CHANGED`. On any failure no plan is written and the previous plan stays current.
9. **Background run.** As proposed in the Phase 0 architecture record: an in-process worker (bounded pool, default 1 per API process, no new queue infrastructure) and a status endpoint the client polls. At most one queued/running run per round (DB partial unique index). On API start, runs left `running` are marked failed ("interrupted").
10. **Atomic, versioned commit.** The worker locks the round row, re-reads `input_version` and recomputes the fingerprint. If either changed during the solve, the run ends `stale` (`INPUTS_CHANGED`) and nothing is written (A14). Otherwise, in one transaction: insert plan version N+1, mark it current, supersede the previous one, replace the round's `assignments` (one owner per order) and run `validate_plan` against the persisted rows. Every input mutation from 2A/2B takes the same round-row lock, so a mutation and a commit can never interleave.
11. **Bounds.** Solver: insertion + Guided Local Search bounded by 1,000 solutions, 30 s safety limit per strategy (spike settings); a non-`SUCCESS` status is shown as a warning. Round size is capped (`ROUND_TOO_LARGE`) at conservative limits chosen from the 2B local measurements, recorded in the 2B report (100 orders / 8 riders was only a proposal; Q6). The spike configured Valhalla for 2,500 matrix pairs; 100 orders + 2 depots + 8 endpoints is ~12,100 pairs per profile, so the local limit is raised and memory/latency are measured.
12. **Order statuses and plan replacement (corrected 17 Oct 2026).** Optimization is **not** refused because some orders are Postponed or Completed; the proposed "all orders must be Pending" rule (Q1) was never approved and is not built. A run plans every **Pending** order. **Completed** orders keep their history and existing owner and are never re-planned or reassigned. **Postponed** orders keep their existing owner and stay off the active sequence (D08), counting toward that rider's capacity. A case that would need later-phase behaviour (for example reassigning a Postponed or Completed order, or a Postponed order with no owner) gets an explicit coded "unsupported" response, and the existing data is left unchanged. Any input change after a plan is issued marks that plan **out of date** (current `input_version`/fingerprint ≠ the plan's) without changing it. No automatic rerouting and no endpoint-change reoptimization (R23 is Phase 4). Operational replanning policy (Q1–Q2) stays pending.
13. **Rider visibility.** Riders keep the Phase 1 list of their assigned orders, now filled by the plan's assignments. Sequenced cards, next stop and navigation are Phase 3.

### Schema (migration `0003_phase2b_planning.py`)

| Table | Columns and constraints |
|---|---|
| `delivery_rounds` (changed) | `mode` CHECK IN ('equal','smart','manual') DEFAULT 'smart' |
| `orders` (changed) | `locked_rider_id` → riders nullable (manual lock; must be a participating rider, checked in precheck); `first_priority` bool DEFAULT false. Both bump `version` and the round's `input_version` |
| `planning_runs` (new) | `id`; `round_id`; `state` CHECK IN ('queued','running','succeeded','failed','stale'); `requested_by`; timestamps; `input_version`; `input_fingerprint`; `error_code`; `error_details` JSONB (order codes / rider names only); `plan_id` nullable; partial UNIQUE (`round_id`) WHERE state IN ('queued','running') |
| `route_plans` (new) | `id`; `round_id`; `version`; UNIQUE (`round_id`,`version`); `mode`; `input_fingerprint`; `distance_label`; `provenance` JSONB (provider, `real_road`, `recorded`, profiles, data date, attribution, solver strategy/status/objective/metric); `warnings` JSONB; `is_current` with partial UNIQUE (`round_id`) WHERE `is_current`; `created_by`; `created_at` |
| `plan_routes` (new) | PK (`plan_id`, `rider_id`); `vehicle`; `profile` CHECK IN ('motor_scooter','motorcycle'); `start_kind`; `endpoint_kind`; `open_route` bool; `road_distance_m`, `road_duration_s` (real edges only) |
| `plan_stops`, `plan_stop_orders` (new) | Stop ≠ order (keeps Phase 4 grouping possible without a migration; Phase 2 never groups because `building_id` is never set). `plan_stop_orders` UNIQUE (`plan_id`,`order_id`) enforces one owner per order per plan |
| `assignments` (changed) | add `plan_id` → route_plans; still PK `order_id` |

No Home/Custom coordinates are copied into plan tables; the plan records the endpoint kind, and the fingerprint ties it to the exact confirmed version.

### Files

- New package `routewise_api/routing/`: `domain.py`, `gate.py`, `planner.py`, `matrix/{base,recorded,valhalla_local}.py` (ported from the spike at `fcac55e`, attribution header), `engine.py` (one Valhalla `Actor` per process behind a lock; tile path from `ROUTEWISE_VALHALLA_TILES`; recorded matrices are injected by tests only, never selectable through configuration), `adapter.py` (DB rows → domain round; uses `planning_input()`), `runs.py` (worker, commit, stale detection, interrupted-run recovery).
- New: `routers/admin_planning.py` (or section of `admin.py`), `migrations/versions/0003_…py`, tests listed below.
- Changed: `requirements.in`/`requirements.lock` (add `ortools==9.15.6755`, `pyvalhalla==3.9.1`, the versions accepted in Phase 0, both with cp314 macOS arm64 wheels), `config.py` (provider, tile path, worker count, size cap), `main.py` (worker lifecycle), `models.py`, `orders.py` (lock/priority edits), `tests/test_permissions.py`, `tools/mutation_check.py`, `docs/DEVELOPMENT.md` (build tiles with `spikes/valhalla/build_tiles.sh`, point the API at them).
- Unchanged: everything under `spikes/` and `tests/fixtures/`.

### API

| Method and path | Purpose |
|---|---|
| `PUT /api/admin/rounds/{id}/mode` | equal / smart / manual |
| `PUT /api/admin/orders/{id}/lock`, `POST /api/admin/rounds/{id}/locks` (bulk, for manual mode) | Set or clear an owner lock (expected versions) |
| `PUT /api/admin/orders/{id}/priority` | First-delivery flag |
| `POST /api/admin/rounds/{id}/optimize` | Precheck → 202 `{run_id}`; 409 gate not ready / run already queued or running; 422 infeasible or unsupported input; 503 engine unavailable or planning queue full |
| `GET /api/admin/planning-runs/{run_id}` | State, error code and details |
| `GET /api/admin/rounds/{id}/plan`, `…/plans`, `…/plans/{version}` | Current plan (with `out_of_date`), version list, a past version |

### Acceptance criteria (roadmap gate)

- Missing endpoint confirmations block the API (A12, API half).
- Fixed starts, rider-specific fixed ends and open Last-stop routes are exactly as configured in every plan.
- Capacities are never exceeded; every order has exactly one owner in every mode (A13); manually locked assignments survive planning.
- Priority orders are each the first stop of their route, or the run fails with `PRIORITY_CONFLICT`.
- No silent omissions: a plan contains every order or no plan is written.
- A change to a status, endpoint, lock, priority, pin, depot or rider setting during a solve prevents that solve's commit (A14).
- Plans are real-road only: provenance `real_road = true`; a missing edge is never zero; Last-stop sink never counted.
- The port gives the spike's results on the recorded DU matrices.

### Meaningful tests

- **Parity:** the ported planner reproduces the spike's initial-plan results (smart, equal and manual assignments and distance labels) recorded in `spikes/routing/evidence/scenario_run_du-{motor_scooter,motorcycle,fleet}.json`, and matches the spike's own planner output (sequences, objective) when both run on the recorded DU matrices.
- **Planner invariants (recorded DU matrices, many generated rounds):** `validate_plan` clean for every mode; mixed fleet uses the right matrix per rider (a scooter rider's distance equals the `motor_scooter` matrix sum, a bike rider's the `motorcycle` sum); open route distance excludes the sink; asymmetric legs priced in the travelled direction.
- **Missing roads:** an injected `NO_ROUTE` edge is never used and never priced 0; a fully isolated pin → `UNROUTABLE_LOCATION`; an isolated Home endpoint → `UNROUTABLE_ENDPOINT` naming the rider; a matrix with no real provenance (synthetic) is refused by the API.
- **Infeasibility:** one test per code, asserting no plan row, assignments unchanged, previous plan still current.
- **Gate through the API:** optimize with one unconfirmed rider → 409, no run row created.
- **Stale plans (real PostgreSQL):** a test hook pauses the worker after solving; an endpoint change, status change, lock change and order pin edit each make the run `stale` with nothing written; with no change it commits version N+1.
- **Concurrency:** two optimize requests for one round → one run, the other 409; a commit racing an input mutation is serialized by the round-row lock (same technique as Phase 1 `test_concurrency.py`).
- **Persistence:** DB rejects two current plans per round and an order in two routes of one plan; assignments match the current plan exactly; interrupted runs are marked `interrupted` on start, never successful.
- **Plan replacement and statuses:** re-optimizing gives version N+1 (the previous version is kept and superseded). With Postponed and Completed orders present, optimization still runs: Completed history and Postponed ownership are preserved exactly, and only Pending orders are planned. An operation that would reassign a Postponed or Completed order gets an explicit unsupported response, with data unchanged.
- **Provider failure:** missing tiles / Valhalla error → `ROUTING_ENGINE_UNAVAILABLE`, previous plan kept, no fallback provider.
- **Permissions/privacy:** inventory, roles, CSRF on every new mutation; plan responses and run errors carry no Home/Custom coordinates; logs carry no customer fields.
- **Live (opt-in `ROUTEWISE_LIVE_TESTS=1`, local tiles):** a 20-order DU round with a scooter and a bike rider on real local Valhalla: provenance real, not recorded; both profiles used; every leg ≥ 0.8 × straight line − 300 m (spike check); benchmark at 20/50/100 orders (matrix latency, solve time, memory) saved to `docs/phase2/evidence/`.
- **Targeted defect checks (not an exhaustive mutation run):** zero-cost missing edge, sink counted as distance, gate bypass, lock ignored, capacity off-by-one, priority not first, stale commit accepted, bicycle/car profile mapping, recorded provider allowed in production.

---

## 5. Step 2C — admin planning screens and end-to-end verification

### Behaviour (mobile-first, same Shell, Tailwind and API client as Phase 1)

**Admin**
- **Office & Warehouse settings:** label, coordinates or Maps link, "Check this pin in Google Maps" link, outside-area warning (Phase 1 pattern).
- **Round → Riders:** participation toggle, vehicle, capacity, start; version conflicts shown as in the order editor.
- **Round → Destinations:** each participating rider's endpoint kind and confirmation state; Home/Custom shown as "Home (private)" / "Custom destination", no coordinates.
- **Round → Orders (existing page):** owner lock selector and first-delivery toggle per order; bulk owner assignment for manual mode.
- **Round → Plan:** mode selector; readiness checklist (orders, depots, riders, destinations); **Optimize** disabled with the listed reasons until ready (A12, UI half); run progress via polling; error panel per code with order codes / rider names and the fix needed; result per rider: start → ordered stops (order code, customer, product) → end kind, road distance in km and duration labelled "traffic-free estimate", provenance label and "© OpenStreetMap contributors"; warnings (equal band unmet, solver status); "Plan out of date" banner; version history and, for a re-plan, which orders changed rider.
- **No map view** in Phase 2: there is no ₹0 tile source suitable beyond development and public tile servers must not be relied on (Q8). The plan is a list.

**Rider (the only rider-facing change in Phase 2)**
- A "My destination for this round" card on the existing rider page: the five options, coordinates or Maps link for Home/Custom, Save, then Confirm; shows confirmed / not confirmed. Sequenced delivery cards, calling, navigation and status actions remain Phase 3.

### Files

- New: `apps/web/src/pages/{RoundPage,PlanPage,DepotsPage}.tsx`, `src/components/{RiderConfigTable,DestinationStatus,PlanRoutes,PlanErrors,EndpointCard}.tsx`, `e2e/phase2.spec.ts`, `src/*.test.ts` for new client helpers.
- Changed: `src/App.tsx` (routes), `src/api.ts` (typed calls, polling), `src/components/Shell.tsx` (navigation), `src/pages/{OrdersPage,RiderPage}.tsx`, `scripts/e2e_setup.py` and `scripts/e2e.sh` (seed riders, depots and a DU fixture whose synthetic customers sit on the 17 public DU points; e2e server uses the recorded DU provider, labelled recorded).
- Docs: `docs/phase2/PHASE2-REPORT.md`, `docs/phase2/evidence/`, `docs/phase2/screenshots/`, `docs/DEVELOPMENT.md`; proposed tracker changes written in the report only (Notion paused).

### Acceptance criteria

- With one unconfirmed rider the Optimize button is disabled with that rider named, and a direct API call returns 409 (A12, both halves).
- Full round in the browser: import → configure three riders (scooter and bike, both starts) → each rider confirms a different destination including Last stop and Custom → optimize → plan shows every order exactly once with road distances and provenance (A13).
- A destination change while the run is in progress produces "inputs changed, run again", and the old result is not shown as current (A14).
- Each infeasibility code shows an actionable message, and no partial plan appears.
- Works at 390 px with touch and at 1280 px; keyboard reachable; no customer data or rider coordinates in browser storage (Phase 1 client rule).
- Real-road integration: one opt-in run of the same flow against local Valhalla tiles succeeds and is evidenced.

### Meaningful tests

- Playwright, desktop and mobile: (1) gate blocked then unblocked, (2) full plan in smart, equal and manual, (3) stale run during a destination change, (4) capacity and priority conflict messages, (5) rider sees only own destination card and own assigned orders after planning; (6) opt-in live local-Valhalla run.
- Vitest: polling stops on terminal states; mutations carry CSRF; no browser storage.
- Screenshots (synthetic data) inspected by hand for every new screen, both widths.
- Full regression (section 6) and an updated mutation-check total.

---

## 6. Regression run at the end of each step

| Suite | Command | Must stay |
|---|---|---|
| API | `cd services/api && .venv/bin/python -m pytest -q` | all pass (150 Phase 1 tests plus new) |
| Spike (accepted reference, includes reroute and same-building tests) | `cd spikes/routing && .venv/bin/python -m pytest -q` | 264 passed, 5 skipped, unchanged |
| Local Valhalla live | `ROUTEWISE_LIVE_TESTS=1 … -m live tests/test_valhalla_du.py` | 2 passed |
| Frontend | `npm run typecheck`, `npx vitest run`, `npm run build` | pass |
| Browser | `scripts/e2e.sh` | Phase 1 and Phase 2 specs pass |
| Defect injection | `tools/mutation_check.py` on a scratch copy | every injected defect caught |

## 7. Outside this plan's immediate scope (existing tests preserved)

Rider delivery cards, next-stop, dialer and Navigate (Phase 3); quick call, postpone-and-reroute, current-position / last-completed origins, endpoint-change reoptimization (R23), same-building grouping (Phase 4); offline list, outbox and sync (Phase 5); retention purge (D10), CI, deployment, HTTPS, backups, real-device testing. The spike's `reroute.py` and building tests keep running unchanged in every regression run; the plan schema keeps stop ≠ order so Phase 4 needs no destructive migration.

## 8. Unresolved decisions and blockers

Each row is a **pending proposal, not an owner-approved decision**. Q3, Q4 and Q5 were applied in step 2A because the owner's 2A instructions asked for exactly that behaviour; Q1 is explicitly not to be implemented without approval.

| # | Question | Proposed default | Blocks |
|---|---|---|---|
| Q1 | Can the admin re-optimize a whole round after a plan is issued? | Pending. Proposal: only while every order is Pending. **Not to be implemented without owner approval** (owner, 2A instructions) | later |
| Q2 | What happens when a rider changes destination after a plan is issued? | Change saved, confirmation reset, plan marked out of date; no automatic reroute until Phase 4 | 2B |
| Q3 | May the admin see a rider's Home/Custom coordinates? | No; kind and confirmation state only (R24) | 2A |
| Q4 | May the admin set or confirm a destination for a rider without a phone? | No; the rider chooses and confirms (R09) | 2A |
| Q5 | Should rider accounts be created in the admin UI? | No in Phase 2; keep the Phase 1 CLI | 2A |
| Q6 | Pilot batch size / optimization cap (open since Phase 0) | Cap at the largest size measured on real Valhalla in 2B, starting at 100 orders / 8 riders | 2B |
| Q7 | Snap-distance threshold for pins far from a road | Measure on DU points in 2B; propose ~200 m, owner to confirm | 2B |
| Q8 | Map display of routes | None in Phase 2 (list view); a ₹0 tile source is a later decision | 2C |
| B1 | Real Office and Warehouse locations | Owner enters them in the local app (never committed); development and tests use public DU points | 2A real use; not tests |
| B2 | Valhalla tiles must exist locally to plan | Built by `spikes/valhalla/build_tiles.sh` (git-ignored, OSM data to 2026-10-11); unit and e2e tests use recorded DU matrices | live checks only |
| B3 | `motorcycle` costing is beta upstream | Accepted Phase 0 limitation; reported in plan provenance | none |
| B4 | No CI or remote | Local runs only, as in Phase 1 | none |
| B5 | Phase 1 carry-overs (real phones, Safari/Firefox, live short links, retention) | Remain open; Phase 2 adds rider Home coordinates to the retention scope | none for Phase 2 |
