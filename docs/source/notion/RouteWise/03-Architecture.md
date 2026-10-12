# Architecture and technology decisions

[Home](../RouteWise.md) · [Decisions](08-Decisions.md)

**State:** proposed implementation architecture. Documentation verification is not a successful application test.

## Technology choices

| Area | Recommendation | Verified evidence / remaining work |
|---|---|---|
| IDE and coding assistant | Existing Cursor on Mac; Claude Code in integrated terminal | Cursor observed running. CLI returned version 2.1.296. Login/entitlement and IDE extension not checked. Anthropic documents Cursor support. |
| Web app | React + TypeScript + Tailwind; Vite candidate | Fits the requested stack. Pin mutually compatible versions when scaffolding; no packages installed here. |
| API | FastAPI; Python 3.12 candidate isolated runtime | System Python is 3.14.3. Do not change system Python; verify OR-Tools and import-library compatibility in a project environment. |
| Database | PostgreSQL + migrations | Proposed. Hosting, version, backups and credentials pending. |
| Solver | OR-Tools in a backend service | Official examples support different starts and ends per vehicle. Our constraints and open endpoints still need a spike. |
| Matrix provider | Provider adapter exposing directed distance/time matrices | Pending coverage, motorbike mode, pricing, limits, cache/display rights and real trial. Google Routes is a candidate, not an approved vendor. |
| Map UI | Leaflet with compatible tiles/data, or provider-compatible alternative | Pending. Do not put Google Routes content on a Leaflet map without a compatible license/architecture. |
| Import | Pandas + openpyxl | Proposed. Prefer .xlsx baseline; validate file-size, row-count and parsing limits. Legacy .xls support requires a separate compatibility decision. |
| Auth | Server-managed secure sessions and role checks | Required. Proposed same-origin API for simpler secure cookies and CSRF protection. No authentication implementation yet. |
| Offline | Service worker app shell + IndexedDB own-rider snapshot/outbox | Proposed. Sensitive API responses do not go into generic shared caches. Test iOS and Android behavior. |
| QA | pytest; frontend component tests; Playwright end-to-end tests | Proposed. Device pilot and real API evidence are additionally required. |
| Delivery | Private GitHub repository; CI; HTTPS staging and production | Planned only. Vendor, budget, domain and repository are not created or selected. |

## Verified facts that affect the design

- OR-Tools accepts vehicle-specific start/end indices. It optimizes supplied costs; it does not supply road distances. [Official routing examples](https://developers.google.com/optimization/routing/routing_tasks).
- Google Compute Route Matrix returns pair-level distances/durations. Read status and route-existence fields; a failed pair is not a zero-cost edge. Limits and modes must be checked for the actual request. [API reference](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRouteMatrix).
- Google's TWO_WHEELER mode is for motorized two-wheelers. The documentation describes region limitations and beta guidance. This does not prove suitable matrix coverage for the startup's area. [Two-wheeler routing](https://developers.google.com/maps/documentation/routes/route_two_wheel).
- Google Routes has display/attribution and storage restrictions. This is a selection constraint for Leaflet and offline architecture, not a claim that the desired combination is already approved. [Provider policies](https://developers.google.com/maps/documentation/routes/policies).
- Claude Code can be used from Cursor; the CLI also works in the integrated terminal. [Official IDE guide](https://code.claude.com/docs/en/vs-code).

## System responsibilities

```text
Admin/Rider PWA
    ↕ HTTPS, secure session, versioned requests
FastAPI application
    ├── role and order-ownership authorization
    ├── import validation + guarded location resolution
    ├── round/assignment/status service ↔ PostgreSQL
    ├── planning service → matrix-provider adapter → road API
    └── planning service → OR-Tools → versioned route plan

Rider browser only
    ├── service worker: app shell
    ├── IndexedDB: own saved list + pending status operations
    └── tel: link / Google Maps navigation handoff
```

Keep API credentials server-side. Decide whether optimization needs a background job only after measuring realistic runtime; do not add infrastructure without evidence. The client shows progress and can safely retry using idempotency keys.

## Proposed data model

| Entity | Key data / invariant |
|---|---|
| User / Session | Role, active state, secure credential/session reference; no client-trusted role |
| Rider | User reference; configured vehicle and capacity |
| Location | Coordinates, source, resolution state, optional normalized building identifier |
| DeliveryRound | Imported batch, participating riders, distribution choice, planning version |
| RoundRider | Start, endpoint choice/location, endpoint confirmation version, capacity snapshot |
| Order | Internal ID, customer name, product text, contact, instructions, location, one of three statuses, version |
| Assignment | Round, order, rider; exactly one owner for every assigned order |
| RoutePlan / RouteStop | Rider, plan version, sequence, start/end, stop-to-order membership |
| StatusOperation | Unique operation ID, actor, order/version, old/new status, server acknowledgment |

A navigation stop is not an order. Group only validated shared entrances/buildings; nearby coordinates alone are insufficient. Keep grouping within a rider's assignments during rerouting. Initial optimization may group a building if capacity and manual locks permit; never move packages merely to produce one shared stop across riders. Capacity counts underlying orders, not grouped stops.

## Routing contract

1. Validate round locations, capacities, active riders and endpoint confirmations. A removed rider does not count toward the confirmation gate.
2. Build a directed road-cost matrix for orders/stops, starts and fixed endpoints. Account for different vehicle profiles where relevant. Keep the original road-distance units and provider metadata in permitted evidence storage.
3. Model each rider's own start and fixed end. For Last stop, test a zero-cost virtual sink/open-route construction; do not report that artificial edge as real driving distance.
4. Apply manual ownership locks, capacity counted in orders, equal-count targets when selected, and first-priority constraints. Detect incompatible priorities or insufficient capacity with an actionable error.
5. Use a bounded solve; report feasible result and objective without promising a proven global optimum. No silent dropped orders, unreachable zero edges or Euclidean distances disguised as road costs.
6. Commit a plan atomically only if inputs are still the same version. A concurrent endpoint/status change invalidates stale output.
7. For rider reroutes, freeze assignment ownership and completed deliveries; solve only that rider's active remainder from a confirmed origin and their current endpoint.

## Session and offline contract

Use HttpOnly, Secure cookies with suitable SameSite settings, server-side revocation and CSRF protection. Enforce Admin/Rider authorization on every endpoint, including import, optimization and status mutation. Offline access is to a previously authenticated saved snapshot, not a new offline login.

The outbox records operation ID, order ID, expected version, transition, actor and local time. Server time and authorization determine accepted state. Duplicate replay returns the same acknowledgment. Conflicting versions require reconciliation; a stale queued transition cannot silently undo completion. Retain unsent operations through normal reload, but protect shared-device logout/account switching and communicate that logging out with unsynced changes may discard data. Decide the precise expiry and clearing policy in Phase 0.

## Open decisions before implementation

Service area and two-wheeler coverage; routing/map vendor and spending limit; exact package versions; pilot batch sizes; equal-mode conflict policy; priority conflicts; Postponed reinsertion; cache expiry; session lifetime; data retention; deployment location. Record evidence and choice in the decision database. No private locations or vendor secrets are assumed.
