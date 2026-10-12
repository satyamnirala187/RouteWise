# Phase 0 acceptance results

> **Accepted by the owner on 13 October 2026 for local development** at `2a34226` ([owner acceptance record](OWNER-ACCEPTANCE-2026-10-13.md)). This is the current accepted baseline: local Valhalla + OpenStreetMap for DU North Campus, Delhi, with D04–D10 approved as recorded there. The text below is the historical record as written before acceptance. Its "in review / not complete" statements describe that time and are kept unchanged. Phase 1 work is reported in [../phase1/PHASE1-REPORT.md](../phase1/PHASE1-REPORT.md).

## Evidence sets (read this first)

| Evidence set | Revision | Area and data | Tests at that revision |
|---|---|---|---|
| **Original Phase 0 spike: historical** | `f6c479e` | Bengaluru public points (test area only); OSRM public demo, car profile, response recorded 2026-10-12T15:59:58Z | 114 passed, 2 skipped; 13/13 injected defects caught |
| Optional Stadia adapter (inactive, mocked only) | `a6c2875` | No live calls | +27 mocked tests |
| **Delhi implementation: current** | the commit titled "Add local Valhalla routing evaluation for DU North Campus" (the commit directly after `a6c2875`; see `git log`) | DU North Campus, Delhi (confirmed area); local self-hosted Valhalla on OSM data up to 2026-10-11T20:21:06Z | 264 passed, 5 skipped (all checks run on the Bengaluru recording plus DU `motor_scooter` and `motorcycle`); 23/23 injected defects caught |

Results from one set are never reported as results of another. Bengaluru evidence files are unchanged since `f6c479e`.

**Current status: Phase 0 is not complete** (owner review, D04 provider, production host, D05–D10 and sign-off pending).

## Update — 13 October 2026: confirmed area DU North Campus, local Valhalla (₹0)

The owner confirmed the delivery area (DU North Campus, Delhi), a **₹0** routing budget, and no paid services. Local, self-hosted Valhalla on OpenStreetMap data was evaluated: see [VALHALLA-LOCAL.md](VALHALLA-LOCAL.md). The rows further down are the results as tested at `f6c479e` and are kept unchanged. This table records what changed. **Revision for this update:** the commit titled "Add local Valhalla routing evaluation for DU North Campus" (the commit directly after `a6c2875`; see `git log`).

| # | Updated result | Evidence |
|---|---|---|
| 1 | **Passed.** The core environment is unchanged. Local Valhalla tooling is pinned in `requirements-valhalla.lock` (pyvalhalla 3.9.1, osmium 4.3.1). No manual install was needed | [ENVIRONMENT.md](ENVIRONMENT.md), [VALHALLA-LOCAL.md](VALHALLA-LOCAL.md) §1–3 |
| 2 | **Passed with local Valhalla** (`motor_scooter` and `motorcycle`), with real directed matrices on 16 public DU points: 240/240 routable pairs and asymmetries up to 2.4 km. The provider is still **not formally selected** (D04 is an owner decision). Google/Stadia live checks remain BLOCKED but are optional and inactive | `valhalla_du_capture.json`, `test_valhalla_du.py` |
| 3–8 | **Passed on DU data too.** Every planner check runs on Bengaluru OSRM (historical) plus DU Valhalla scooter and motorcycle. Mixed fleet: each rider is planned on its own vehicle profile | 264 passed / 5 skipped; `scenario_run_du-*.md` |
| 9 | **Passed.** The local adapter is tested with a fake engine (errors, nulls, bicycle refused). New: real unroutable pins are reported as `UNROUTABLE_LOCATION` before solving | `test_valhalla_du.py`, `test_unreachable_labels.py` |
| 10 | Unchanged (passed offline; live short link not run) | — |
| 11 | **Evidence updated; decision pending.** Self-hosted Valhalla has ₹0 licence cost and no per-request fee. Local resource use is measured. **A production host within ₹0 is unresolved** (owner decision) | [VALHALLA-LOCAL.md](VALHALLA-LOCAL.md) §3, §6; [PROVIDER-COMPARISON.md](PROVIDER-COMPARISON.md) |
| 12 | Unchanged (proposal awaiting decisions). Self-hosting removes the provider caching restrictions; ODbL attribution applies | [OFFLINE-PRIVACY.md](OFFLINE-PRIVACY.md) |

Phase 0 is **still not complete.** The owner must review the gates, decide D04 (provider), D05–D10 and the production host, and sign off.

## Results as tested at `f6c479e` (12 October 2026, Bengaluru, historical)

Run on 12 October 2026 by Claude Code (automated), on the Mac described in [ENVIRONMENT.md](ENVIRONMENT.md).

**Tested implementation revision:** `f6c479e` (`f6c479e5b2a8fecf60919e18f119cf39ad21b352`, local branch `main`, not pushed). The results below were produced on the working tree that became this commit. They were then re-verified on 2026-10-12T16:45Z from a `git archive` export of `f6c479e` with a fresh venv: `run_phase0.sh` exit 0, 114 passed, 2 skipped; the live OSRM test passed and the Google test was skipped as BLOCKED; scenario output identical to the committed evidence. **Fixtures:** public Bengaluru landmarks with synthetic roles (`tests/fixtures/public_locations_bengaluru.json`) and a recorded real OSRM response (`tests/fixtures/recorded/osrm_bengaluru_car.json`, captured 2026-10-12T15:59:58Z).

**Commands:** `./run_phase0.sh` gave 114 passed, 2 skipped. `ROUTEWISE_LIVE_TESTS=1 pytest -m live` gave 1 passed (OSRM) and 1 skipped (Google BLOCKED). The mutation check (`tools/mutation_check.py`) caught 13 of 13 injected defects.

**At that time, Phase 0 was not complete.** Criterion 2 is blocked for the selected two-wheeler provider, criterion 11 is blocked on the live Google trial and the owner's spending decision, and human review has not happened.

| # | Criterion | Result | Evidence (tests in `spikes/routing/tests/`) | Notes / remaining |
|---|---|---|---|---|
| 1 | Reproducible environment | **Passed** | [ENVIRONMENT.md](ENVIRONMENT.md); `test_runtime_matches_pinned_lock`; clean run of `run_phase0.sh` from an export of `f6c479e` (74 files, fresh venv, same scenario output) | — |
| 2 | Real road matrix | **Passed with OSRM car proxy · Blocked for the selected two-wheeler provider** | [osrm_live_capture.json](../../spikes/routing/evidence/osrm_live_capture.json): profile, timestamp, units, 256 elements, `HTTP 200 code Ok`, 4 directed asymmetries > 2 km; `test_recorded_matrix_is_real_directed_and_complete`; `test_live_osrm_returns_real_asymmetric_road_matrix` | Google `TWO_WHEELER` live trial: [BLOCKED](../../spikes/routing/evidence/google_routes_check.json), no key or spend approval. Car profile ≠ motorbike |
| 3 | Separate starts and ends | **Passed** | `test_each_rider_starts_and_ends_where_requested` (3 riders, 12 orders, Office and Warehouse starts, Home/Custom/Last-stop ends); [scenario run](../../spikes/routing/evidence/scenario_run_recorded.md) | Run on the real matrix (recorded replay and live) |
| 4 | Endpoint options and gate | **Passed** | `test_all_five_endpoint_options[office/warehouse/home/custom/last_stop]`; `test_last_stop_adds_no_artificial_return_trip`; `test_initial_optimization_waits_for_valid_confirmed_endpoints` (5 cases); `test_removed_rider_does_not_block_the_gate`; `test_api_boundary_blocks_until_every_rider_confirms` (HTTP 409 → 200) | API boundary is the spike FastAPI app, not Phase 1 |
| 5 | Assignment and capacity | **Passed** | `test_every_order_assigned_exactly_once_in_every_mode[equal/smart/manual]`; `test_equal_mode_balances_counts_and_smart_mode_minimises_road_distance`; `test_mixed_capacities_are_respected`; `test_manual_mode_keeps_admin_assignments_and_only_sequences`; `test_manual_lock_survives_automatic_modes`; `test_insufficient_total_capacity_is_explained_not_dropped`; `test_locks_beyond_capacity_and_to_inactive_riders_are_rejected` | The equal-mode conflict policy is a soft band plus a warning (D07 proposal) |
| 6 | Priority | **Passed** | `test_priority_order_is_first_active_delivery_on_its_route` (8 cases); `test_priority_with_lock_goes_first_on_the_locked_rider`; `test_one_priority_per_rider_route_allows_three`; `test_conflicting_priorities_are_reported_explicitly` | D05 semantics are recorded as proposed; owner to confirm |
| 7 | Rider-only reroute | **Passed** | `test_postpone_and_reroute_changes_only_that_riders_active_sequence`; `test_origin_fallback_is_explicit`; `test_endpoint_change_reroutes_only_that_rider`; `test_provider_failure_keeps_last_valid_plan`; `test_stale_plan_cannot_overwrite_newer_state` | Ownership and other riders' plan versions are compared before and after |
| 8 | Same-building model | **Passed** | `test_same_building_orders_share_one_stop_but_count_two_capacity_units`; `test_building_group_counts_two_capacity_units`; `test_proximity_alone_does_not_group`; `test_manually_split_building_is_not_merged`; `test_shared_stop_partial_completion_keeps_independent_statuses` | — |
| 9 | Failure handling | **Passed (mocked around actual adapters)** | `test_matrix_google.py` (rate limit, invalid key, permission, 5xx, timeout, non-JSON, malformed/missing/out-of-range elements, `ROUTE_NOT_FOUND`, element errors); `test_matrix_osrm.py`; `test_unreachable_labels.py` (forbidden edges avoided, isolated stop → explicit error, synthetic label) | A live invalid-key check against Google is blocked along with criterion 2 |
| 10 | Map link resolution | **Passed (offline / mocked fetch) · live short link Not run** | `test_linkresolve.py`: coordinate URLs, place pin over camera, ambiguous/text links, short-link redirect parsing, private-network DNS, unsafe redirects, loops, broken links, manual pin | No public sample short link was supplied. DNS-to-connect TOCTOU hardening is listed for Phase 1 |
| 11 | Provider decision | **Blocked** (evidence recorded; decision pending) | [PROVIDER-EVALUATION.md](PROVIDER-EVALUATION.md): coverage (India supported, beta), limits, prices, element projections for 20/50/100 orders, OSRM latency 497 ms per 256 elements; [cost_projection.md](../../spikes/routing/evidence/cost_projection.md) | Google latency not observed; spending cap ($0 trial proposed) and D04 need the owner |
| 12 | Offline/privacy architecture | **Proposed, awaiting decision** | [OFFLINE-PRIVACY.md](OFFLINE-PRIVACY.md) | Expiry, retention and logout values need owner approval (D09/D10). Implementation is Phase 5 |

## Tracker cases A01–A06 (as tested at `f6c479e`, historical; see the update table for DU)

| ID | Case | Result | Evidence |
|---|---|---|---|
| A01 | Real road matrix | **Blocked** (OSRM real-road check passed; selected two-wheeler provider blocked) | Criterion 2 row |
| A02 | Vehicle-specific starts and ends | **Passed** | Criterion 3 row |
| A03 | Last stop open route | **Passed** | `test_last_stop_adds_no_artificial_return_trip` |
| A04 | Capacity and assignment modes | **Passed** | Criterion 5 row |
| A05 | Priority conflicts | **Passed** | `test_conflicting_priorities_are_reported_explicitly` |
| A06 | Missing road edge and provider errors | **Passed** | Criterion 9 row |

Spike-level evidence also exists for later-phase cases A09/A10 (link resolution), A12 (gate), A13 (single owner), A14 (stale plan), A18/A20/A21 (reroute, endpoint change, shared stop). **Those cases stay "Not run"** until they are re-tested in the real application in their own phases.

## Known limits of the `f6c479e` evidence

- Durations are free-flow car estimates from OSM data, not traffic-aware and not two-wheeler specific.
- The 20/50/100-order runtime benchmark used a synthetic matrix (timing only).
- The spike has no authentication, persistence or UI. Those are Phase 1 onward.
- Route quality is a bounded heuristic result (GLS, 1,000 solutions), not a proven optimum.
