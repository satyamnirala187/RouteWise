# Step 2B report: local road planning, runs and versioned plans

**Date:** 17 October 2026, corrected 18 October 2026 (section 0a) · **Prepared by:** Claude Code · **Status: 2B implemented, awaiting review.** Phase 2 is **not complete**: step 2C (screens and end-to-end verification) and the final Phase 2 review remain. Recorded in one local commit (2B and its correction pass); nothing pushed or deployed; ₹0 spent; Notion not accessed.

**Base:** step 2A commit `13de7829685094a2d82beffff676862ec01f81f0` (Phase 1 accepted at `fcac55e`). **Revision:** all 2B work, including the 18 October correction pass, is in the local commit *"Add RouteWise road planning and versioned route plans"*, directly after `13de782` (see `git log`). It has not been pushed. **Scope:** backend/API only. No planning screens, navigation, calling, operational rerouting, same-building grouping or offline work.

## 0. Plan correction made first

[The plan](IMPLEMENTATION-PLAN.md) still contained a test saying optimization must be refused once any order is Postponed, plus a matching "409 round in progress" response. That blanket restriction was never approved, so I removed both. Behaviour item 12 now describes the status rules actually built (section 2 below). Q1, "re-plan only while every order is Pending", is marked pending and **not implemented**. The plan's 2B section also gained a note listing where the implementation differs from it.

## 0a. Correction pass (18 October 2026)

Review found two problems. Both are fixed; the figures in sections 3 and 6 are from after the fix.

**1. A deactivated rider's plan could stay labelled valid.** The CLI deactivated accounts without advancing any round's `input_version`, and plan responses derive `out_of_date` only from `input_version`. An in-flight run was already caught by the fingerprint, but a plan saved *before* the deactivation kept `out_of_date: false`.

Fix: one shared operation, `routewise_api/accounts.py::deactivate_user`, which the CLI now calls (the rules are not duplicated in the CLI). It:
- revokes the account's sessions, as before;
- advances `input_version` of every round the rider currently participates in, once each. Saved plans of those rounds become `out_of_date` in the current-plan, history and per-version responses, and any in-flight run ends `stale` (`INPUTS_CHANGED`);
- takes the same lock order as plan commits (depots `FOR SHARE` → affected rounds `FOR UPDATE`, sorted → user row `FOR UPDATE`), so it serialises with the commit's final check (section 3);
- re-reads the rider's rounds once the user row is held, and if the rider joined another round meanwhile, rolls back and retries with that round locked too;
- does not touch assignments, statuses or plan rows: Postponed ownership and Completed history are kept, and the round simply needs re-planning (readiness reports `account_inactive`; optimize is refused with `NOT_READY`);
- does nothing to rounds when the account is already inactive, or for an admin account.

`set-password` still revokes sessions but changes no planning input; display-name changes were already excluded from the fingerprint. Neither invalidates a saved plan or makes a run stale (tested).

To make account state part of the locked input, `planning.capture` now reads the participating riders' user rows `FOR SHARE`, after the round lock. A deactivation that the commit's final check has already passed therefore waits until the plan is committed, then marks it out of date.

**2. The surviving "commit without the round lock" mutant was a real gap, and my earlier explanation of it was wrong.** I had written that the commit still blocks on the round through the plan's foreign key. It does not: that foreign key takes `KEY SHARE` on the round row, and an edit's `UPDATE … SET input_version` takes `FOR NO KEY UPDATE`, which does not conflict with it. The old race test held the round row externally, so both the commit (already past its check) and the edit waited on it. Whichever went first, it accepted "succeeded and out of date", including the non-serial order where the edit committed first and the plan then overwrote assignments computed from older input.

New test `test_an_edit_racing_the_commit_after_its_final_check_has_a_serial_outcome` pauses the worker inside its commit transaction, after the final capture and check and before any plan or assignment write (`hooks["before_write"]`, tests only). It then races 8 kinds of planning-input edit against that point: pin, status, lock, priority, destination, capacity, mode and depot. It accepts only serial outcomes:
- **edit committed first:** the run must be `stale`, plan 1 must stay current and assignments unchanged;
- **plan committed first:** the edit must succeed, and plan 2 must be current and `out_of_date`.

With the explicit lock the edit always waits, so the second outcome is the one that happens. Without it, 7 of the 8 edits commit while the plan is paused and the plan then overwrites assignments: the test fails with "plan saved over an input change committed before it". The depot edit stays serialised even without the round lock, because it takes the depot row `FOR UPDATE`, which conflicts with the commit's `FOR SHARE`. The mutant is now caught; I did not weaken any assertion.

## 1. What was implemented

**Routing core** (`routewise_api/routing/`)
- The accepted spike modules are ported with an attribution header: the domain model, endpoint gate, OR-Tools planner, matrix types and the local Valhalla adapter. `spikes/` is unchanged.
- Two marked changes to the planner:
  - Only depots that a rider actually uses must exist. The spike required both.
  - A start or fixed destination with no road connection for that rider's profile is reported as `UNROUTABLE_ENDPOINT` with the rider's name. Previously that surfaced as a generic infeasible solve.
- The spike's in-memory `PlanStore` is replaced by the PostgreSQL commit.
- **Parity is exact.** In all six DU evidence cases (scooter-only, motorcycle-only and mixed fleet, each in smart and equal mode), the port reproduces the spike's recorded assignments and per-route kilometres. The manual-mode case and ten seeded random rounds reach identical objectives in both planners.

**Roads**
- Valhalla runs in-process (pyvalhalla 3.9.1) on the locally built OSM tiles: `spikes/valhalla/data/valhalla_tiles`, or `ROUTEWISE_VALHALLA_TILES`.
- Profiles: scooter → `motor_scooter`, bike → `motorcycle`. There is no bicycle, car or straight-line option, no paid service and no public demo service.
- Each profile present gets one directed matrix, and each rider is priced with their own profile.
- A `NO_ROUTE`/`ERROR` element becomes a forbidden arc, never a usable zero.
- Last stop is an open route. Its artificial final arc costs 0 for the solver and is never added to reported distance or duration.
- A plan is saved only if every matrix has `real_road = true`. A synthetic matrix fails the run with `NOT_ROAD_DISTANCES`.
- Missing tiles give `503 ROUTING_ENGINE_UNAVAILABLE` before anything is queued.
- **Recorded matrices are test-only.** They are injected on `app.state.planning.provider_override` and cannot be selected through configuration.

**Planning inputs** (admin API)
- Distribution mode: `equal`, `smart` (default) or `manual`.
- Owner locks, one order at a time or in bulk. Bulk locks are all-or-nothing, with version checks.
- First-delivery priority, for Pending orders only.
- Every edit advances the round's `input_version`.
- The admin order view now includes `planning: {locked_rider_id, first_priority, assigned_rider_id}`.

**Optimization (`POST /api/admin/rounds/{id}/optimize`)**

These checks all happen **before anything is scheduled**:
- The 2A readiness gate: order pins, depots, rider setup, current confirmations and active accounts.
- The status rules in section 2.
- The size limits.
- The spike's prechecks: capacity, invalid or excess locks, manual mode needing an owner for every order, and priority conflicts.

Errors are coded and name orders and riders only. If everything passes, the request captures an in-memory snapshot of all planning inputs, stores a `queued` run with its `input_version` and a keyed fingerprint (HMAC-SHA256 with the server secret), and returns **202**.

**Worker**
- One planning thread per API process, and at most 4 queued runs beyond the running ones. A slot is reserved before the run row exists; when none is free the response is `503 PLANNING_BUSY`.
- At most one queued or running run per round: checked under the round lock and backed by a partial unique index.
- Matrices and solving run with **no database transaction open**.

**Commit**
- The commit re-locks the planning input and recaptures it. It saves only if both `input_version` and the fingerprint are unchanged. Otherwise the run ends `stale` (`INPUTS_CHANGED`) and the previous plan and assignments are untouched.
- In one transaction it writes: plan version N+1 as current, the previous plan as superseded, routes, plan orders, and assignments linked to the plan.
- It then re-reads everything and rolls back on any disagreement.

**Recovery**
- On start-up, queued or running runs are marked `interrupted`. Their snapshots lived only in the old process's memory.
- A run still queued or running after 15 minutes is reported `interrupted` when read.
- Unfinished work is never marked successful.

**Plans**
- Current plan, history and past versions.
- `out_of_date` is shown when the round's `input_version` has moved on since the plan's snapshot.
- Each route lists its stops in order, plus its held Postponed and Completed orders.
- Each plan records road distance and traffic-free duration, provenance, warnings and ownership changes against the previous plan. Provenance covers the provider, profiles, `real_road`/`recorded`, OSM attribution and data note, and solver status and strategy.

**Privacy**
- Snapshots, which contain Home/Custom coordinates, exist only in memory.
- Runs, plans, errors, provenance and logs carry order codes, rider names or ids and destination kinds, never destination coordinates. This is tested.
- Logs carry run ids, codes and exception types only.

### Endpoints added

| Method and path | Purpose |
|---|---|
| `PUT /api/admin/rounds/{id}/mode` | Distribution mode |
| `PUT /api/admin/orders/{id}/lock` · `POST /api/admin/rounds/{id}/locks` | Owner lock (single / bulk, all-or-nothing) |
| `PUT /api/admin/orders/{id}/priority` | First delivery |
| `POST /api/admin/rounds/{id}/optimize` | Validate → 202 run; 409 `NOT_READY`/`RUN_IN_PROGRESS`; 422 coded infeasible/unsupported; 503 `ROUTING_ENGINE_UNAVAILABLE`/`PLANNING_BUSY` |
| `GET /api/admin/planning-runs/{run_id}` · `GET /api/admin/rounds/{id}/planning-runs` | Run state, error code, message and details, timings |
| `GET /api/admin/rounds/{id}/plan` · `…/plans` · `…/plans/{version}` | Current plan, history, a past version |

All are admin-only, with server-side checks. Every mutation needs the session CSRF token and an allowed Origin.

**Error codes:**
- Before scheduling: `NOT_READY`, `ORDERS_NOT_READY`, `CONFIGURATION_NOT_READY`, `RUN_IN_PROGRESS`, `NOTHING_TO_PLAN`, `ROUND_TOO_LARGE`, `INSUFFICIENT_CAPACITY`, `HELD_ORDERS_EXCEED_CAPACITY`, `INVALID_LOCK`, `LOCK_EXCEEDS_CAPACITY`, `MANUAL_ASSIGNMENT_MISSING`, `PRIORITY_CONFLICT`, `PRIORITY_NOT_PENDING`, `OWNERSHIP_CHANGE_UNSUPPORTED`, `POSTPONED_WITHOUT_OWNER`, `OWNER_NOT_PARTICIPATING`, `STALE_ORDERS`, `ROUTING_ENGINE_UNAVAILABLE`, `PLANNING_BUSY`.
- In a run: `UNROUTABLE_LOCATION`, `UNROUTABLE_ENDPOINT`, `NO_FEASIBLE_PLAN`, `NOT_ROAD_DISTANCES`, `ROUTING_ENGINE_UNAVAILABLE`, `INPUTS_CHANGED`, `INTERRUPTED`, `INTERNAL`.

## 2. Order statuses and ownership

Optimization is never refused just because some orders are Postponed or Completed.

| Order | What a run does |
|---|---|
| **Pending** | Planned exactly once: the active sequence, with a new or the same owner. Re-planning may move a Pending order to another rider unless it is locked; each move is listed in `summary.ownership_changes` |
| **Postponed** with an owner who still participates | Kept with that owner and off the active sequence (D08). It counts toward the owner's capacity. Its assignment is unchanged; only its plan link moves |
| **Completed** with an owner who still participates | History: kept with that owner, counted toward capacity, never re-planned |
| **Completed** without an owner, or whose owner was removed | Left as is (no assignment created or changed) and listed in the plan summary |
| A lock that would give a Postponed or Completed order to a **different** rider | `422 OWNERSHIP_CHANGE_UNSUPPORTED`, from the lock endpoint or before scheduling. Nothing changes |
| **Postponed without an owner** | `422 POSTPONED_WITHOUT_OWNER`: set it back to Pending to plan it. Nothing changes |
| **Postponed owned by a removed rider** | `422 OWNER_NOT_PARTICIPATING`: reassigning it would need a handover workflow, which is not built. Nothing changes |
| A rider whose held orders exceed their capacity | `422 HELD_ORDERS_EXCEED_CAPACITY` |

Statuses are never reset. The commit re-checks that no Completed order's owner changed.

## 3. Locking strategy

| Operation | Lock order |
|---|---|
| 2A rider setup and destination writes, confirmations, **optimize requests**, **plan commits** | both depot rows `FOR SHARE` (a depot edit takes its row `FOR UPDATE`) → round `FOR UPDATE` → round-rider or run rows |
| Order edits: text, pin, link, status, **lock, priority**; bulk locks | order rows `FOR NO KEY UPDATE` (sorted by id) → `UPDATE` of the round's `input_version` |
| Mode change | round row only |
| **Account deactivation** (`accounts.deactivate_user`, used by the CLI) | both depot rows `FOR SHARE` → every round the rider participates in, `FOR UPDATE`, sorted by id → user row `FOR UPDATE` |
| Inside optimize requests and plan commits, after the round lock | participating riders' user rows `FOR SHARE` (`planning.capture`) |
| Password change (CLI) | user row and its sessions only; not planning input |
| Reading an overdue run | that run row only |

**One change to Phase 1 code.** Order edits used `FOR UPDATE`. A plan commit holds the round lock and, through its foreign keys, needs a `KEY SHARE` lock on the orders it writes. An edit holding `FOR UPDATE` on an order while waiting for the round lock would therefore deadlock with the commit. Order edits now use `FOR NO KEY UPDATE`: it still serialises concurrent order edits but doesn't conflict with `KEY SHARE`, so no wait cycle remains. A targeted defect check confirms this: switching back to `FOR UPDATE` makes the race tests fail.

No transaction is open during matrix generation or solving. The stale check compares both `input_version` and the keyed fingerprint.

**What the commit's locks guarantee** (all tested, section 6):
- **The explicit round lock is required.** Every planning-input edit advances `input_version` under the round row, so once the commit's final check has passed, no edit can commit until the plan and its assignments have committed. The edit then marks the new plan out of date. The plan's foreign keys alone give no such guarantee: their `KEY SHARE` lock on the round row does not conflict with an edit's `UPDATE` of `input_version`.
- **The depot `FOR SHARE` locks** additionally serialise depot moves with the commit.
- **The user-row `FOR SHARE` locks** serialise account deactivation with the commit, including for a round the deactivation did not lock. In that case the commit waits, then sees the inactive account and ends `stale`.
- **The fingerprint** still catches changes that bypass the shared operations, such as a direct database update of the account flag (tested). Such a bypass does not advance `input_version`, though, so it cannot mark an already-saved plan out of date. Only the shared operation does that.

## 4. Schema (migration `0003`) and start-up

| Object | Details |
|---|---|
| `delivery_rounds.mode` | CHECK equal/smart/manual, default `smart` |
| `orders.locked_rider_id` (FK riders, indexed), `orders.first_priority` | Owner lock and priority |
| `planning_runs` | State CHECK queued/running/succeeded/failed/stale/interrupted; `input_version`, `input_fingerprint`, mode, error code/message/details, timings; partial UNIQUE (round) WHERE queued or running |
| `route_plans` | UNIQUE (round, version); partial UNIQUE (round) WHERE `is_current`; unique `run_id`; provenance, warnings, summary JSONB (no coordinates) |
| `plan_routes` | PK (plan, rider); CHECKs: vehicle scooter/bike, profile motor_scooter/motorcycle and **matching the vehicle**, start, destination kind, `open_route ⇔ last_stop`, non-negative costs |
| `plan_orders` | PK (plan, order) gives **one entry per order per plan**; FK (plan, rider) → plan_routes; role active/postponed/completed; `stop_seq` present ⇔ active |
| `assignments.plan_id` | FK → route_plans (SET NULL); `order_id` stays the primary key, so each order has one owner |

`0003` was autogenerated, then edited by hand: I named the foreign keys and added the mode CHECK. It upgrades and downgrades cleanly, and a test confirms no schema/model diff.

**Start-up:**
```bash
cd services/api
.venv/bin/python -m pip install -r requirements.lock   # adds ortools 9.15.6755 + pyvalhalla 3.9.1 and their pinned deps
.venv/bin/alembic upgrade head                         # 0001 → 0002 → 0003
../../spikes/valhalla/build_tiles.sh                   # once, if the tiles are missing
```
The new dependencies use exactly the versions accepted in Phase 0. `pip freeze` changed by exactly those 9 packages: absl-py, immutabledict, numpy, ortools, pandas, protobuf, python-dateutil, pyvalhalla and six.

## 5. Local measurements and enforced limits

**Benchmark:** `tools/benchmark_planning.py`, written to [`evidence/local_routing_benchmark.json`](evidence/local_routing_benchmark.json).
- Real local Valhalla and OR-Tools through the same `prepare`/`solve` code the API uses.
- Mixed fleet; destinations cycle through Home, Custom, Last stop, Office and Warehouse.
- Orders are synthetic grid points over DU North Campus. 195 of 196 points were kept; the one with no road connection was dropped.
- Machine: Apple M2 Mac. The run was repeated twice with identical results.

| Orders / riders | Road points | Mode | Matrix (2 profiles) | Solve | Total | Solver |
|---|---|---|---|---|---|---|
| 20 / 3 | 24 | smart · equal | 0.21 s · 0.20 s | 1.0 s · 1.0 s | 1.2 s · 1.2 s | SUCCESS |
| 40 / 4 | 44 | smart · equal | 0.41 s | 2.3 s · 3.5 s | 2.7 s · 4.0 s | SUCCESS |
| 60 / 6 | 64 | smart · equal | 0.67 s | 7.6 s · 12.7 s | 8.3 s · 13.4 s | SUCCESS (equal band missed, see below) |
| 80 / 6 | 84 | smart · equal | 0.91 s | 12.9 s · 23.3 s | 13.8 s · 24.2 s | SUCCESS (equal band missed) |
| 100 / 8 | 104 | smart · equal | 1.25 s | 14.0 s · 18.1 s | 15.3 s · 19.4 s | SUCCESS |
| 120 / 8 | 124 | smart · equal | 1.6 s | 15.6 s · 22.3 s | 17.2 s · 23.8 s | SUCCESS |

- **Matrix size:** the spike configured Valhalla for 2,500 cell pairs. 100 orders + 2 depots + 2 Home/Custom points is 104 points, or 10,816 cells per profile, so the application sets Valhalla's limit to `max_locations²`. Matrices took up to 2 s for 220 points.
- **Memory:** the benchmark process peaked at about 1.35 GB RSS, which includes the 195-point filtering matrices. The API process's memory under planning was **not** measured separately.
- **Equal mode at 60/6 and 80/6** finished within its solution bound **without** reaching the equal band: 10 orders outside it. The plan carries a warning. The spike's warning always blamed "locks/grouping"; the application now says either that locks caused it or that the time-bounded search did not reach an equal split. This is a reproducible solver-quality limitation, not a crash or silent change.

**Application limits, enforced** (`PlanningLimits`):
- 80 Pending orders, 8 riders and 100 road points per run;
- 30 s per solver strategy (the spike's value; at most 3 strategies);
- 1 worker and 4 queued runs per process;
- runs older than 15 min are reported interrupted.

These are conservative local limits chosen from the measurements above. They are **not** owner decisions and not verified for other machines or real pilot data; the 100/8 proposal stays a proposal (Q6).

**Road snapping (Q7) — measured, not enforced.** Valhalla snaps each point to the nearest usable road, and the leg from the pin to that road is **not** included in distances.
- Public DU fixture points snapped 0–98.9 m away (St. Stephen's 98.9 m).
- Synthetic points snapped a median of 14.3 m and at most 261.5 m away.
- The campus-centroid point that Phase 0 found unroutable snaps only 41.6 m away, but onto an isolated internal road.

So snap distance is not a reliable check on its own. No threshold is enforced, and the 200 m figure remains an unverified proposal. Unroutable pins are still caught by the matrix itself (`UNROUTABLE_LOCATION` / `UNROUTABLE_ENDPOINT`).

## 6. Test results (run on this Mac: 17 Oct 2026, and 18 Oct 2026 for the correction pass where stated)

### Completed

| Check | Command | Result |
|---|---|---|
| API suite (real PostgreSQL, recorded real DU matrices, mocked network) | `cd services/api && .venv/bin/python -m pytest -q` | **320 passed, 1 skipped** after the correction pass (18 Oct; 302 passed, 1 skipped on 17 Oct). The skip is the opt-in live test, run separately below. New since 2A: 37 planning, 30 concurrency, 8 account deactivation, 13 parity, 1 permission inventory |
| — planning behaviour: contract, profiles, modes, locks, priority, gates, missing roads, provider failure, statuses, history, constraints, privacy | `tests/test_planning.py` | 37 passed (included above) |
| — concurrency: stale solves for 10 kinds of input change (destination, status, lock, priority, pin, depot move, capacity, mode, deactivation through the shared operation, and a direct account-flag update); untouched input commits; concurrent optimize; commit racing pin/status/depot/destination edits at the round lock; **8 edits racing the commit after its final check (serial outcome only)**; a round the deactivation missed still cannot get a valid plan; rollback; restart and overdue recovery; queue bound; one active run per round | `tests/test_planning_concurrency.py` | 30 passed (included above) |
| — account deactivation through the CLI: after a saved plan (current plan, history and each version report `out_of_date`; sessions end; readiness and optimize blocked); Postponed ownership and Completed history kept; password and display-name changes invalidate nothing; during solving (`stale`); during the final check (deactivation waits for the commit, then the new plan is out of date); deactivation holding its locks first (the commit waits, then ends `stale`); retry when the rider joins a round meanwhile; already-inactive and admin accounts | `tests/test_account_deactivation.py` | 8 passed (included above). These, the concurrency tests and the 2A/Phase 1 race tests passed 3 more times in a row (50 passed each) |
| — spike parity | `tests/test_routing_parity.py` | 13 passed (included above) |
| **Opt-in real local Valhalla**: full API planning run (11 synthetic orders, mixed fleet) | `ROUTEWISE_LIVE_TESTS=1 .venv/bin/python -m pytest -q -m live tests/test_planning_live.py` | **1 passed.** Provenance `valhalla-local (OpenStreetMap data)`, `real_road=true`, `recorded=false`, both profiles; 15 road points, matrices 0.19 s, solve 0.47 s; total 22,848 m, identical to the recorded-matrix result. Recorded in [`step2b_live_valhalla_api.txt`](evidence/step2b_live_valhalla_api.txt), separately from the recorded/mocked tests |
| Phase 0 routing regression (spike unchanged) | `cd spikes/routing && .venv/bin/python -m pytest -q` | **264 passed, 5 skipped** |
| Phase 0 local Valhalla checks | `ROUTEWISE_LIVE_TESTS=1 .venv-valhalla/bin/python -m pytest -q -m live tests/test_valhalla_du.py` | **2 passed** |
| Frontend type checks · unit tests · build (the order response gained `planning`) | `npm run typecheck` · `npx vitest run` · `npm run build` | **OK (exit 0) · 5 passed · OK** |
| Browser regression (Phase 1 spec, desktop + mobile) | `E2E_SHOTS_DIR=<scratch> scripts/e2e.sh` | **8 passed.** Screenshots went to a scratch folder; all 20 committed Phase 1 and 2A screenshots were checksummed before and after: unchanged |
| Targeted defect checks (13, each aimed at one 2B risk; not an exhaustive run) | `tools/mutation_check.py <copy> <python> "2B:"` | **13/13 caught** after the correction pass ([`step2b_correction_targeted_defect_checks.txt`](evidence/step2b_correction_targeted_defect_checks.txt)). The original 10: order edits back on FOR UPDATE (deadlock), stale result committed, fingerprint not compared, **commit without the round lock**, missing road priced zero, bike routed as scooter, Postponed re-planned, held orders ignored in capacity, synthetic matrix accepted, unfinished runs not recovered. Three new: deactivation does not bump rounds, deactivation skips the participation recheck, capture without the account lock. A focused re-run of the round-lock mutant shows the new commit-point test failing for 7 of its 8 edits (all but the depot edit), and the deactivation commit-first test failing with a detected deadlock. **The 17 Oct run was 9/10**, with the round-lock mutant surviving ([`step2b_targeted_defect_checks.txt`](evidence/step2b_targeted_defect_checks.txt), kept). The explanation I gave for that survival was wrong (section 0a) |

Raw outputs: `docs/phase2/evidence/step2b_*.txt` and `local_routing_benchmark.json`; the correction pass adds `step2b_correction_api_pytest.txt` and `step2b_correction_targeted_defect_checks.txt`.

**Not re-run in the correction pass:** the live Valhalla run, the routing parity and Phase 0 regression, and the frontend and browser checks. The corrections change no routing, matrix, solver, response-shape or frontend code. The only planning change is a row lock inside `capture` plus a test-only hook; parity and every planning test ran again in the full API suite. Their 17 Oct results above stand.

### Problems found and fixed along the way

- **Deadlock:** the plan commit's foreign-key `KEY SHARE` locks against order edits' `FOR UPDATE`. Fixed by switching order edits to `FOR NO KEY UPDATE` (section 3).
- **Misleading equal-mode warning:** it blamed locks when there were none.
- **Gap: account deactivated mid-solve.** There was no test. Test added on 17 Oct; on 18 Oct this was found to be incomplete, because a plan saved *before* a deactivation stayed labelled valid. Fixed in the correction pass (section 0a).
- **Wrong lock analysis (18 Oct):** the round-lock mutant's survival was a missing test, not an equivalent mutant. Fixed in the correction pass (section 0a).
- **Gap: held orders' share of capacity.** Untested. Test added.
- **Benchmark filter:** it dropped every point when one point was isolated.
- **Test-only issues:** a run-list ordering tie under the frozen test clock, the provenance label format, and a test assuming Rider C always gets orders.

### Skipped or not run

- Planning screens and browser tests of planning (2C). Every 2B behaviour is tested through the API only.
- An exhaustive mutation run (deliberately not repeated; the targeted checks are above).
- Planning memory of the API process; benchmarks on other machines; real pilot data and real road-quality checks with riders.
- Real phones, Safari/Firefox, CI, deployment (carried over).

## 7. Limitations and remaining work

1. **API only.** Admin planning screens, the rider destination card and browser-level verification are 2C.
2. **Equal mode can miss the equal band** within the bounded search at some sizes (60/6 and 80/6 here). The plan warns, but doesn't retry with a larger search.
3. **Re-planning moves unlocked Pending orders between riders.** This is reported in `ownership_changes` and is not prevented. Whether issued ownership should be frozen is the pending policy question (Q1/Q2). Admins can lock owners to keep them.
4. **Snap legs are not costed.** No snap-distance threshold is enforced (Q7 pending). Road access and gate quality still need checking with real riders.
5. **Durations are traffic-free** estimates. There is no ETA feature.
6. **One API process per database.** Start-up recovery marks every unfinished run interrupted, and the queue bound is per process.
7. **The `motorcycle` costing is beta upstream** (accepted Phase 0 limitation).
8. **Not built: rerouting, endpoint-change reoptimization, same-building grouping, offline.** The ported planner still carries the spike's grouping code; the application never sets building ids. Retention/purge (D10) is also still not implemented, and plans now add data that a purge must cover.
9. **Limits are local and conservative.** They are not owner-approved, and Q6 and Q7 remain open.
10. **Account changes must go through the shared operation.** A direct database edit of `users.active` still makes in-flight runs stale (fingerprint) but does not mark already-saved plans out of date. There is no reactivation command; reactivating an account would also need to go through a shared operation that advances `input_version`.
11. **Deactivation does not end a rider's participation or hand over their orders.** The round stays blocked (`account_inactive`) until an admin turns that rider's participation off. Postponed orders they own then hit `OWNER_NOT_PARTICIPATING`, since a handover workflow is not built.

## 8. Changed files and Git state

**Git:** branch `main`. Everything below is in the local commit *"Add RouteWise road planning and versioned route plans"*, directly after `13de782`. Nothing pushed or deployed; no remote exists.

**New:**
- Routing core: `services/api/routewise_api/routing/` (`__init__`, `domain`, `gate`, `planner`, `matrix/__init__`, `matrix/base`, `matrix/valhalla_local`)
- `services/api/routewise_api/planning.py`, `services/api/routewise_api/routers/admin_planning.py`, `services/api/routewise_api/accounts.py` (correction pass)
- `services/api/migrations/versions/0003_phase2b_planning.py`
- Tests: `services/api/tests/{planning_world,recorded_matrix,test_planning,test_planning_concurrency,test_routing_parity,test_planning_live,test_account_deactivation}.py`
- `services/api/tools/benchmark_planning.py`
- Docs and evidence: `docs/phase2/STEP-2B-REPORT.md`, `docs/phase2/evidence/{local_routing_benchmark.json, step2b_api_pytest.txt, step2b_live_valhalla_api.txt, step2b_phase0_regression.txt, step2b_targeted_defect_checks.txt, step2b_web_typecheck.txt, step2b_web_vitest.txt, step2b_web_build.txt, step2b_e2e_playwright.txt, step2b_correction_api_pytest.txt, step2b_correction_targeted_defect_checks.txt}`

**Modified:**
- API code: `services/api/routewise_api/{config,main,models,orders}.py`, `services/api/routewise_api/cli.py` (deactivate and set-password through `accounts`), `services/api/routewise_api/routers/admin.py` (admin order view, and `FOR NO KEY UPDATE` on order edits)
- API packaging and tooling: `services/api/{pyproject.toml (live marker), requirements.in, requirements.lock}`, `services/api/tools/mutation_check.py` (13 targeted 2B mutants, prefix filter)
- Tests: `services/api/tests/{conftest,test_migrations_privacy,test_permissions}.py`
- Web: `apps/web/src/api.ts` (`AdminOrder.planning` type)
- Docs: `README.md`, `CLAUDE.md`, `docs/README.md`, `docs/DEVELOPMENT.md`, `docs/phase2/IMPLEMENTATION-PLAN.md` (plan correction, status, 2B differences)

**Not modified:** `docs/source/`, `spikes/`, `tests/fixtures/`, Phase 0, Phase 1 and 2A evidence, reports and screenshots.
