# Phase 0 architecture decision record (proposed)

**State:** proposed, for owner review. This record is backed by the spike in `spikes/routing/`. It does not change the confirmed scope (D01) or the selected add-ons 2/4/8/9.

## 1. Stack after compatibility checks

| Layer | Phase 0 finding | Proposal |
|---|---|---|
| Python runtime | OR-Tools 9.15.6755, FastAPI 0.143.0, pandas 3.0.6 and openpyxl 3.1.5 install and run on **Python 3.14.3** (arm64) | Use 3.14 in an isolated venv; no 3.12 runtime needed |
| Solver | OR-Tools handles per-rider starts and ends, open routes via a virtual sink, capacity, locks and priority | Keep OR-Tools in the API service |
| Matrix provider | Adapter interface proven with Google Routes (mocked) and OSRM (live) | **Pending D04**; see [PROVIDER-EVALUATION.md](PROVIDER-EVALUATION.md) |
| Map display | Google forbids showing Routes results on non-Google maps | Leaflet only if D04 picks an OSM-based provider; otherwise Google Maps JS. **Pending D04.** |
| Web | Node 24.18.1 present | React/TypeScript/Tailwind/Vite versions are pinned in Phase 1 (not checked in Phase 0) |
| Database | PostgreSQL not installed locally | Decide local install vs container in Phase 1 (unchanged) |

## 2. Routing model (as implemented in the spike)

- **Nodes are navigation stops, not orders.** A stop groups orders with the same validated `building_id`, the same entrance location and the same manual owner. Proximity alone never groups. A stop's demand equals its order count (D06), and a building larger than any rider's capacity is split.
- **Per-rider start and end.** Office/Warehouse starts. Office, Warehouse, Home and Custom are fixed end nodes. **Last stop** is a per-rider virtual sink with zero-cost arcs, which are never added to reported road distance.
- **Missing edges.** A `NO_ROUTE` or `ERROR` element is removed from the successor domain, never priced at 0. Synthetic matrices are always labelled `SYNTHETIC — NOT ROAD DISTANCES`.
- **Modes (D07).** *Smart* minimises total road distance. *Equal* adds soft per-rider bounds on order count (a water-filling band within capacity). The penalty dominates distance, and an unmet band is reported as a warning. *Manual* requires an admin owner for every order and only sequences. Manual locks also work in Smart and Equal.
- **Priority (D05).** A first-priority stop may only follow a route start, enforced by removing it from every other stop's successor domain. Two priority stops locked to one rider, or more priority stops than riders, produce `PRIORITY_CONFLICT` before solving.
- **No silent drops.** There are no disjunctions, so every order is mandatory. Infeasibility returns a coded error (`INSUFFICIENT_CAPACITY`, `LOCK_EXCEEDS_CAPACITY`, `INVALID_LOCK`, `MANUAL_ASSIGNMENT_MISSING`, `UNRESOLVED_LOCATION`, `PRIORITY_CONFLICT`, `NO_FEASIBLE_PLAN`). An independent `validate_plan` checks every result: one owner per order, capacity, locks, starts/ends, priority first.
- **Gate (R10).** Initial optimization refuses to run unless every *active* rider has a confirmed endpoint, and Home/Custom need a resolved location. Removed riders do not count. This is enforced in the planner and, in the spike API, returns HTTP 409 with rider ids and reasons only (no coordinates).
- **Rider reroute (R17–R19, R23).** Only the rider's Pending orders are re-solved, from a confirmed origin to the current endpoint. Other riders' route objects are reused unchanged, and the assignment table is asserted identical. Postponed orders stay assigned and visible but leave the sequence until set back to Pending (D08). If the provider fails, the last valid plan is returned, marked "Awaiting recalculation".
- **Origin choice (R18).** A fresh GPS position is used first. Otherwise the last completed stop is used and labelled as a fallback. With neither, the rider must confirm a pin or their configured start.
- **Versioning.** Plans carry an input fingerprint. `PlanStore.commit` rejects a plan whose inputs changed during the solve, or whose version is not newer.

### Solver configuration finding

The cheapest-arc first-solution strategy closes Last-stop routes immediately, because the virtual sink costs 0. It then backtracked for 3–20 s on locked or priority cases, and in one case found no solution at all. The spike therefore uses **local cheapest insertion + Guided Local Search, bounded by 1,000 solutions**, with a wall-clock safety limit. This is deterministic across runs (two runs compared identical) and solved all cases. Objectives were equal or better than greedy descent, e.g. base scenario 38,761 m → 37,644 m.

Measured solve times on this Mac (synthetic matrix, timing only; [benchmark](../../spikes/routing/evidence/solver_benchmark.md)): **~1 s at 20 orders, ~5–6 s at 50, ~12–14 s at 100 orders.**

**Implication for Phase 2:** the architecture said to decide on a background job "only after measuring realistic runtime". At 50–100 orders, synchronous HTTP is uncomfortable. The proposal is an in-process task with a status endpoint and client polling, with no new queue infrastructure, and a revisit if pilot sizes demand it.

## 3. Proposed persistence schema (Phase 1/2 starting point)

This follows the documented data model, with the constraints the spike showed are needed:

```text
users(id, role ∈ {admin, rider}, active, password_hash, created_at)
sessions(id, user_id, created_at, expires_at, revoked_at, csrf_secret)          -- server-side, revocable
riders(id, user_id → users, display_name)
locations(id, lat, lng, source ∈ {link_pin, query, geo, manual_pin, depot}, state ∈ {resolved, needs_correction}, building_id NULL)
depots(round_id, kind ∈ {office, warehouse}, location_id)
delivery_rounds(id, mode ∈ {equal, smart, manual}, plan_version, state)
round_riders(round_id, rider_id, vehicle ∈ {scooter, bike}, capacity > 0, start ∈ {office, warehouse}, active,
             endpoint_kind, endpoint_location_id NULL, endpoint_confirmed_at NULL, endpoint_version)
             CHECK (endpoint_kind NOT IN ('home','custom') OR endpoint_location_id IS NOT NULL)
orders(id, round_id, customer_name, product_text, contact_text, instructions NULL, location_id NULL,
       status ∈ {Pending, Postponed, Completed}, locked_rider_id NULL, first_priority, version, completed_at NULL)
assignments(round_id, order_id UNIQUE, rider_id)                                  -- exactly one owner
route_plans(id, round_id, rider_id, version, input_fingerprint, origin_kind, origin_location_id,
            distance_label, provider_meta jsonb, created_at)
route_stops(plan_id, seq, location_id, building_id NULL)
route_stop_orders(plan_id, seq, order_id)                                         -- stop ≠ order
status_operations(op_id UUID PRIMARY KEY, actor_id, order_id, expected_version, old_status, new_status,
                  client_time, server_time, result)                               -- idempotent replay
```

Rider-facing reads always filter by `assignments.rider_id = session.rider_id`. A Home endpoint location is readable only by its rider and admins.

## 4. Session and authorization approach

This is unchanged from the architecture document and is restated as the Phase 1 plan; it was **not implemented in Phase 0**:
- Same-origin API with HttpOnly, Secure, SameSite=Lax session cookies; server-side session rows (revocable); per-session CSRF token on mutations; login throttling; modern password hashing (Argon2id proposed).
- Every endpoint checks role and order ownership server-side, including import, optimization and status changes.
- Offline access uses a previously authenticated snapshot, never an offline login. See [OFFLINE-PRIVACY.md](OFFLINE-PRIVACY.md).

## 5. Map-link resolution approach (R05)

Implemented in `linkresolve.py` and tested:
- Full Google Maps URLs are **parsed offline and never fetched**. A destination requires an explicit pin (`!3d…!4d…`, `q=`/`query=`/`destination=` coordinates, `geo:`). A camera centre (`@lat,lng,zoom`, `ll=`) or address text needs manual correction, because no geocoding is done here.
- Only `maps.app.goo.gl` and `goo.gl` are contacted, over HTTPS on the default port, reading the `Location` header only, with at most 3 redirects. Each hop's DNS answers must all be public addresses. Credentials in the URL, IP-literal hosts, non-default ports, scheme downgrades and redirects off the allowlist are rejected.
- **Residual risk for Phase 1:** the DNS check and the HTTP connection resolve separately (time-of-check/time-of-use). Pin the connection to the vetted IP, or route it through an egress proxy, before production. Live short-link resolution was **not run**, because no public sample short link was supplied.
