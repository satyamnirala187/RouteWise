# Phase 0 report — discovery, architecture and routing spike

**Date:** 12 October 2026 · **Prepared by:** Claude Code · **Status: in review, NOT complete.** The live check against the selected two-wheeler provider is blocked, and owner sign-off is required.

## Evidence sets (read this first)

| Evidence set | Revision | Area and data | Tests at that revision |
|---|---|---|---|
| **Original Phase 0 spike: historical** | `f6c479e` | Bengaluru public points (test area only); OSRM public demo, car profile, response recorded 2026-10-12T15:59:58Z | 114 passed, 2 skipped; 13/13 injected defects caught |
| Optional Stadia adapter (inactive, mocked only) | `a6c2875` | No live calls | +27 mocked tests |
| **Delhi implementation: current** | the commit titled "Add local Valhalla routing evaluation for DU North Campus" (the commit directly after `a6c2875`; see `git log`) | DU North Campus, Delhi (confirmed area); local self-hosted Valhalla on OSM data up to 2026-10-11T20:21:06Z | 264 passed, 5 skipped (all checks run on the Bengaluru recording plus DU `motor_scooter` and `motorcycle`); 23/23 injected defects caught |

Results from one set are never reported as results of another. Bengaluru evidence files are unchanged since `f6c479e`.

## Update — 13 October 2026: Delhi implementation (still in review, NOT complete)

**Revision:** the commit titled "Add local Valhalla routing evaluation for DU North Campus" (the commit directly after `a6c2875`; see `git log`).

**Owner constraints:** the delivery area is **DU North Campus, Delhi**; the routing/service budget is **₹0**; no paid subscriptions or billable services. In response:

- **Stadia was corrected and set inactive** (commit `a6c2875`). Its matrix needs the $80/month plan, and persisting a Stadia-derived sequence is unresolved under its terms, so that earlier advice was withdrawn.
- **Local Valhalla (OpenStreetMap) evaluated on this Mac with no manual install.**
  - pyvalhalla 3.9.1 + pyosmium 4.3.1 in an isolated venv.
  - Buffered Delhi extract: about 31 × 29 km, built from the full India extract because the box crosses a Geofabrik zone boundary.
  - Tiles: 51 MB, built in 3.6 s; a 17 × 17 matrix takes 61–93 ms.
  - Details, resources, attribution and limitations: [VALHALLA-LOCAL.md](VALHALLA-LOCAL.md).
- **Real directed road matrices for scooter and motorcycle profiles**:
  - 16 public DU points with OSM-sourced coordinates (gates and metro stations preferred).
  - Every existing check passes on them, as it does on the historical Bengaluru matrix.
  - The planner now supports **per-vehicle profiles** (scooters → `motor_scooter`, bikes → `motorcycle`).
- **Findings from real data:**
  1. A campus-centroid pin (Daulat Ram) is unroutable, so the planner now reports `UNROUTABLE_LOCATION` with the order id before solving.
  2. The buffer matters: a naive campus-only clip loses 10 routes and lengthens 18.
  3. India's country polygon is degenerate in the Geofabrik extract, so `build_tiles.sh` sets left-hand traffic explicitly. **Observation for the tested pairs only:** across the 210 directed point-to-point pairs compared (each profile), no distance or time changed. This is not a general claim about how the driving side affects Valhalla routing; other pairs, turn costs elsewhere and turn-by-turn guidance were not tested.
- **Tests:** 264 passed, 5 skipped (opt-in live / blocked paid providers). Local Valhalla live tests gave 2 passed, live = recorded. The mutation check caught **23/23** injected defects (`spikes/routing/evidence/mutation_check.txt`).
- **Still open:**
  - D04 provider selection (self-hosted Valhalla is proposed).
  - A ₹0 production host.
  - Scooter vs motorcycle profile choice.
  - D05–D10.
  - Field validation of OSM data against real rider routes.
  - Owner sign-off.

Phase 1 has not started.

## Original report for `f6c479e` (Bengaluru, historical)

> Everything from here to the end of this file is the original 12 October report for `f6c479e`, kept as written except for this note. Its next steps are partly superseded by the ₹0 budget and the Delhi update above (e.g. the Google trial is no longer planned).

### Phase and revision

Phase 0 only; Phase 1 was not started. **Tested implementation revision: `f6c479e`** (`f6c479e5b2a8fecf60919e18f119cf39ad21b352`) on local branch `main`. There is no remote, and nothing has been pushed. A clean export of that commit was re-run on 2026-10-12 with identical results (see below). `5c533a8` changed documentation only. `a6c2875` (Stadia adapter) and the Delhi commit change code, and are described in the update above, not here. The original documentation package was not modified: SHA-256 checksums of all its files matched before and after the work.

### Delivered behaviour

A reproducible routing spike (`spikes/routing/`), built on OR-Tools 9.15 and Python 3.14.3, that:

- plans **multiple riders with different starts and endpoints** (Office/Warehouse starts; Office, Warehouse, Home, Custom and Last-stop ends) on **real road distances** from OpenStreetMap via OSRM, with provenance labels everywhere;
- **refuses initial optimization until every active rider has confirmed a valid endpoint**, in the planner and at an HTTP boundary (409);
- supports **equal, smart and manual** distribution, manual ownership locks, capacities counted in orders and **first-delivery priority**, with explicit coded errors instead of dropped orders;
- treats **same-building orders as one navigation stop** that keeps separate orders, statuses and capacity units;
- **reroutes one rider** (after postpone/complete, or an endpoint change) from a fresh GPS position, an explicitly labelled last-completed-stop fallback, or a rider-confirmed origin, leaving other riders' routes and all package ownership unchanged;
- never turns a missing road edge into zero, and never labels synthetic or straight-line costs as road distances;
- includes a guarded Google Maps link resolver with manual-pin fallback and private-network protection, a Google Routes adapter (mocked), an OSRM adapter (live), and a cost/volume projection.

Example output on the real matrix (smart mode, O08 first priority):

- R1, Office → Home: 5 orders, 14.63 km.
- R2, Warehouse → Custom: 5 orders, 14.60 km.
- R3, Warehouse → Last stop: 2 orders, 10.66 km, no return leg.
- Equal mode gives 4/4/4 orders and 44.58 km total, versus 39.89 km for smart.

Full output: [scenario_run_recorded.md](../../spikes/routing/evidence/scenario_run_recorded.md).

### Commands run and actual results

| Command | Result |
|---|---|
| `python3.14 -m venv spikes/routing/.venv && pip install -r requirements.in`, then `pip freeze > requirements.lock` | OK; versions in [ENVIRONMENT.md](ENVIRONMENT.md) |
| `python -m routewise_spike capture-osrm` (live) | HTTP 200 `Ok`; 256 elements; 0 no-route; 497 ms; largest asymmetry Forum Mall ↔ Shivajinagar 6,302 m vs 9,001 m |
| `pytest -q` | **114 passed, 2 skipped** (the 2 opt-in live tests) |
| `ROUTEWISE_LIVE_TESTS=1 pytest -q -m live` | 1 passed (OSRM live); 1 skipped: **BLOCKED** (Google key not set) |
| `python -m routewise_spike run-scenario --matrix recorded` and `--matrix osrm-live` | All steps as expected; live and recorded plans **identical**; two recorded runs identical (deterministic) |
| `python -m routewise_spike google-check` | `BLOCKED`, exit 3: no `GOOGLE_MAPS_API_KEY`, no approved spend |
| `python -m routewise_spike cost-projection` | 20/50/100 orders → $313 / $1,443 / $4,465 per month with Google `TWO_WHEELER` (assumptions in [PROVIDER-EVALUATION.md](PROVIDER-EVALUATION.md)) |
| `python -m routewise_spike benchmark` | Solve ~1 s (20 orders), ~5–6 s (50), ~12–14 s (100); synthetic matrix, timing only |
| `tools/mutation_check.py` on a scratch copy | **13 of 13 injected defects caught**, e.g. gate disabled, missing edge → 0, lock ignored, priority ignored, reroute touching other riders, synthetic labelled real, private DNS allowed |
| Clean-checkout reproduction (65 tracked files copied to scratch, fresh venv, `./run_phase0.sh`) | Exit 0; 114 passed, 2 skipped; scenario output byte-identical to the working tree |
| Re-run from `git archive f6c479e` (74 files, fresh venv, `./run_phase0.sh`, then `pytest -m live`) | Exit 0; 114 passed, 2 skipped; live: OSRM passed, Google skipped (BLOCKED); scenario output identical to the committed evidence |

### Failed or not-run checks and limitations

- **Blocked:** live Google Routes `TWO_WHEELER` matrix (criterion 2 for the selected provider, criterion 11 latency and trial). No credentials; spending not approved.
- **Not run:** live short-link resolution (no public sample link); invalid-key behaviour against the real Google API (mocked only).
- **Fixed during the spike:** OR-Tools 9.15's `SetAllowedVehiclesForIndex` binding rejects Python lists, so locks use the `VehicleVar` domain instead. Three first-priority orders across three riders initially found no solution, and locked cases took 3–20 s. The root cause was the cheapest-arc start interacting with the zero-cost Last-stop sink; it is fixed with insertion + GLS bounded by solution count (see [ARCHITECTURE-DECISION.md](ARCHITECTURE-DECISION.md#solver-configuration-finding)).
- **Limits:** OSRM car profile is a proxy for motorbikes; durations are free-flow; the runtime benchmark is synthetic; there is no auth, persistence or UI (later phases). The DNS check and connection in the link resolver are not pinned to the same IP; this is a Phase 1 hardening item.

### Decisions changed or proposed

| ID | Before | Proposal now |
|---|---|---|
| D03 | Python 3.12 candidate | **Python 3.14.3** works with all spike dependencies; no 3.12 needed |
| D04 | Pending | Still **Pending**. Options A–D and a $0 capped Google trial proposed ([evaluation](PROVIDER-EVALUATION.md)). Google forbids Routes results on Leaflet maps |
| D05 | Proposed | Implemented as written (first active stop; conflicts reported). **Confirm** |
| D06 | Proposed | Implemented: order count, and grouped stops keep their order demand. **Confirm** |
| D07 | Proposed | Implemented. Equal = soft count band within capacity, with a warning if locks or grouping prevent it; smart = minimise road **distance** (duration available). **Confirm the metric** |
| D08 | Proposed | Implemented and tested. **Confirm** |
| D09 | Pending | Concrete values proposed ([OFFLINE-PRIVACY.md](OFFLINE-PRIVACY.md)) |
| D10 | Pending | 30-day retention proposed; hosting and spend still open |
| new | — | Optimization runs as an in-process async task with polling (100 orders ≈ 14 s); solver = insertion + GLS, 1,000-solution bound |

### Tasks proposed for status change (owner approves)

P0-01, P0-03, P0-04, P0-05 and P0-06 → **In review**. P0-02 → **Blocked** (Google trial). P0-07 → **In progress** (decisions with owner). P0-08 stays **Not started** until review. Nothing is proposed as Done before human approval. Details: [NOTION-UPDATE-PROPOSAL.md](NOTION-UPDATE-PROPOSAL.md).

### Owner approval and date

*(blank — awaiting human review)*

### Next steps and prerequisites (Phase 1 stays blocked until the gate passes)

1. Owner decides the service area, the pilot batch size and D04 direction, and approves (or declines) a capped Google key for the 36-element trial.
2. Run `google-check --allow-billing --points 6` and the live tests, then record the results against criteria 2 and 11.
3. Owner confirms D05–D08 and the D09/D10 values; supplies one public sample short link if desired.
4. ~~Commit the Phase 0 work so evidence can cite a revision.~~ Done: `f6c479e` (local only, not pushed).
5. Owner reviews this report and signs off. Phase 1 starts only after that.
