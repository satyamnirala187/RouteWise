# Phase 0 — Accepted for local development

**Reviewed:** 13 October 2026. **Area:** DU North Campus, Delhi. **Budget:** ₹0. **Implementation revision:** `2a342264f897aed26fb5476855ed6ab2c6275b3d` (local Git; no remote).

User approved the proposed design defaults in this chat with “Okay, this is fine, go ahead.” Codex completed the local acceptance review after that approval. Phase 0 discovery, architecture and routing spike is complete for the agreed local development scope. Phase 1 is ready to begin; it has not been implemented.

## Verified evidence

- Codex independently reran the committed working tree test suite: **264 passed, 5 skipped**, 13 October 2026. Skips: optional OSRM live test, inactive Google and Stadia providers, two opt-in local Valhalla checks.
- Codex separately ran the two local Valhalla live checks: **2 passed**. Both scooter and motorcycle matrices matched the saved Delhi recordings.
- Claude's saved mutation evidence records **23/23 injected defects caught**; reviewed by Codex, not rerun by Codex.
- Git revision and clean working tree were verified. Historical Bengaluru evidence remains attributed to `f6c479e`; inactive Stadia adapter is `a6c2875`.

## Accepted Phase 0 gates

| Criterion | Review result |
|---|---|
| Reproducible environment | Pinned isolated core and Valhalla environments, scripts and recorded replay documented; original clean-export reproduction recorded by Claude |
| Real roads | Local Valhalla, public Delhi points, directed asymmetry and separate two-wheeler profiles; independent live checks passed |
| Starts/ends and endpoint confirmation | Distinct Office/Warehouse starts, all five endpoints, open Last-stop route, planner/API gate tests pass |
| Assignments/capacity/priority | Equal/smart/manual, owner locks, grouped capacity, infeasibility and priority conflict tests pass |
| Individual rerouting/shared stops | Completed/postponed and origin/endpoint changes retain other riders and package ownership; distinct order statuses retained |
| Provider failures | Error, unreachable and malformed-response tests pass; missing roads are never zero-cost fallback |
| Map-link prototype | Offline parsing and mocked short-link/private-network checks pass. Live short-link test not run; DNS-to-connect hardening remains a Phase 1 requirement |
| Provider decision | Local Valhalla selected for ₹0 local development; coverage, resource use and latency documented. No paid provider or deployment selected |
| Offline/privacy architecture | Approved own-rider storage, expiry, session, replay/conflict and retention defaults; implementation and device tests remain future work |

## Approved decisions

- D04: local Valhalla + OpenStreetMap for DU North Campus, Delhi. Hosted Google/Stadia inactive. No paid services authorized.
- Vehicle mapping: scooter → motor_scooter; motorbike → motorcycle. Motorcycle beta limitation remains documented.
- D05: priority order is the first active stop on its assigned rider's route.
- D06: capacity counts orders, including distinct orders sharing a stop.
- D07: equal balances counts within capacity/grouping/locks; infeasible equality is reported. Smart minimizes road distance. Manual preserves assignments.
- D08: postponed orders retain their rider; explicitly return to Pending for reinsertion.
- D09: own-rider snapshot expires after 18 hours; 12-hour idle and 7-day absolute sessions; versioned idempotent queue; completed orders protected from stale writes; logout warns before unsynced data deletion.
- D10: 30-day customer-detail retention, then purge/anonymize. Public hosting deferred to deployment planning, not asserted free or ready.

## Limits carried forward

No production auth, database, rider UI or offline implementation exists. Road access/gate quality must be checked with real riders during the pilot. Durations are traffic-free estimates; no ETA feature is added. Driving-side edit changed none of 210 tested pairs; broader effects were not tested. Harden map short-link connections against DNS rebinding in Phase 1. No GitHub remote, public demo or background Notion sync exists.

## Source files in the development repository

`docs/phase0/PHASE0-REPORT.md`, `ACCEPTANCE-RESULTS.md`, `VALHALLA-LOCAL.md`, `OFFLINE-PRIVACY.md`; `spikes/routing/evidence/mutation_check.txt`, `valhalla_du_capture.json`; `tests/test_valhalla_du.py`. These are local paths, not public GitHub links.
