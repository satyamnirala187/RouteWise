# Testing and acceptance

[Home](../RouteWise.md) · [Executable tracking template](Acceptance-Cases.csv)

**All application tests are Not run.** The CSV supplies scenarios and expected results, not execution evidence.

## Phase 0 acceptance criteria

1. **Reproducible environment.** Record OS, Python, Node and dependency versions. Use an isolated project environment. A documented command runs the spike from a clean checkout.
2. **Real road matrix.** Use a small set of public locations in a disclosed test area. Capture request profile, timestamp, units, element count, provider response status and permitted redacted evidence. Demonstrate at least one directed-road asymmetry or road detour. Synthetic matrices support unit tests but cannot satisfy this criterion.
3. **Separate starts and ends.** Use at least two riders and eight orders, two candidate start locations and different fixed endpoints. Verify each route starts and ends where requested.
4. **Endpoint options.** Exercise Office, Warehouse, Home, Custom and Last stop using public/synthetic test points. Last stop adds no artificial return trip. Missing/invalid/unconfirmed endpoints block initial optimization at the API boundary.
5. **Assignment/capacity constraints.** Test equal, smart and manual modes; insufficient total capacity; a manually locked order; mixed capacities; and every order assigned exactly once. Explain infeasibility rather than silently dropping orders.
6. **Priority.** The designated first order is the first active delivery on its route. Conflicting first-priority constraints produce an explicit result. Record chosen semantics in D05.
7. **Rider-only reroute.** Mark an order Completed and another Postponed, change the rider origin or endpoint, and verify only that rider's active sequence changes. Compare ownership and other riders' plan versions before/after.
8. **Same-building model.** Model two orders at one entrance, one navigation stop and independent statuses. Count two capacity units under the proposed count model. If ownership is split manually, do not reassign packages merely to merge stops.
9. **Failure handling.** Exercise unreachable pairs, API timeout, rate limit, invalid key and malformed response with mocks around the actual provider adapter. Never turn a missing edge into zero or fall back to straight-line costs under a road-optimized label.
10. **Map link resolution.** Test coordinate URLs, supported short links, ambiguous camera coordinates and broken links. Show manual correction. Block private/loopback destinations and unsafe redirects in server-side link resolution.
11. **Provider decision.** Record local vehicle coverage, matrix limits, latency observations and projected request volumes for 20/50/100 orders. Use `matrix_elements = origins × destinations` for each request, include unique starts/ends and reroutes, then apply current provider pricing. Record actual prices and a proposed spending cap; do not activate paid resources without authorization.
12. **Offline/privacy architecture.** Resolve what may be cached under the selected provider policy; define own-rider data scope, expiry, logout behavior, queue conflict handling and session reauthentication. Keep customer lists out of general caches and private details out of logs.

**Passing Phase 0 requires:** recorded results for these twelve items, all high-priority failures fixed, an architecture decision, and human review of a concise phase report. If live provider access is unavailable, mark that criterion Blocked and the phase unfinished. No app code or spike has been executed in this setup task.

## Evidence format

For each test record: case ID, commit/revision, environment, fixture, action/command, expected result, actual result, Passed/Failed/Blocked, evidence link, tester and timestamp. Redact contacts, addresses, keys and session identifiers. Retain provider evidence only as permitted by its terms. Separate documentation QA from application QA.

## Required later coverage

- Server-side role/ownership authorization; expired/revoked sessions; CSRF and login throttling.
- Import required columns, optional blank instructions, contact preservation, malformed files, unsupported URLs, duplicate review and formula/macro handling.
- Version conflicts between optimization, status change and endpoint change.
- Shared-stop partial completion and postponed return.
- Offline reload, repeated reconnect, duplicate operation replay, out-of-order updates, device clock drift, storage limits and account switching.
- Google Maps and dialer links on actual target phones; accessible controls and small-screen layout.
- HTTPS deployment, database migration, backup restoration and rollback.

## Definition of done

Working behavior meets the requirement; meaningful tests pass; QA evidence is linked to the implementation; no unresolved critical security/data-loss defects; required docs are updated; a human accepts the phase before Notion is updated as complete. A visually convincing prototype alone does not meet the gate.
