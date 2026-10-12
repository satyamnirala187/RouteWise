# Phased delivery roadmap

[Home](../RouteWise.md) · [Tasks](Tasks.csv) · [Acceptance cases](Acceptance-Cases.csv)

All implementation phases are **Not started**. No calendar dates or delivery promises have been assigned. Dependencies define sequence; the owner sets dates when capacity is known.

## Phase 0 — Discovery, architecture and technical spike

**Outcome:** prove the difficult routing assumptions before building screens.

Create an isolated local project, document the schema/auth approach, evaluate real road matrix options, and run a small reproducible routing prototype with mixed starts, rider-specific ends, Last stop, capacity, priority, unreachable pairs and individual reroutes. Assess map-link resolution and safe manual fallback. Record provider terms, estimated usage cost and compatibility with offline data and Leaflet.

**Gate:** all Phase 0 criteria in [Acceptance](06-Acceptance.md) have results and reproducible evidence, open decisions are explicitly resolved or accepted as bounded risks, and the human owner approves the phase summary. A mocked matrix alone cannot pass this phase.

## Phase 1 — Foundation, auth and Excel import

**Depends on:** Phase 0 approval.

Create React/TypeScript/Tailwind and FastAPI foundations, PostgreSQL schema/migrations, secure session auth and role permissions. Build Excel upload with required/optional headings, smart validation, guarded map-link resolution, manual correction and editable customer table/cards.

**Gate:** a valid fixture imports correctly; malformed data has useful row errors; unresolved pins block planning; separate rider sessions cannot access each other's records; secrets stay server-side; migrations and basic CI checks pass.

## Phase 2 — Routing and multi-rider constraints

**Depends on:** Phase 1 approval.

Implement round/rider configuration, scooter/bike profiles, capacities, Office/Warehouse starts, rider endpoint confirmation and admin optimization. Implement equal/smart/manual modes, first-delivery priority, versioned assignments and infeasibility handling.

**Gate:** missing endpoint confirmations block both UI and API; fixed starts/ends and capacity tests pass; every order has one assignment; manually locked assignments survive planning; no silent omissions; real-road integration test succeeds.

## Phase 3 — Rider PWA screens

**Depends on:** Phase 2 approval.

Build mobile rider list and cards with product/instructions, next-stop indication, phone dialer, Google Maps Navigate and Pending/Postponed/Completed actions.

**Gate:** test a complete round on representative phones; links target the intended contact/location; status persists to the server; UI works with touch and keyboard; unauthorized cross-rider requests fail.

## Phase 4 — Quick call, rerouting and shared stops

**Depends on:** Phase 3 approval.

Add quick next-customer availability call, postpone-and-reroute choice, actual-current-position and last-completed-stop origin fallback, rider endpoint-change recalculation and same-building stop grouping.

**Gate:** only the rider's remaining sequence changes; completed orders and other riders' ownership/routes are preserved; denied location permission has an honest fallback; shared-stop orders retain independent statuses; postponed reinsertion works under the chosen rule.

## Phase 5 — Offline PWA, tests, pilot and deployment

**Depends on:** Phase 4 approval.

Implement app shell caching, saved own-rider list, offline status queue and reconnect reconciliation. Test device storage, session expiry, account switching and conflict replay. Configure HTTPS, backups and rollback. Conduct the small human-approved real-delivery pilot and record outcomes.

**Gate:** airplane-mode/reopen/reconnect tests pass without lost or duplicate accepted updates; no offline reoptimization claim; security regressions pass; pilot has actual observations; deployment and restore/rollback evidence exists; owner signs off.

## Completion rule

A task is Done only when its criteria are met, applicable tests have evidence, the link/commit is recorded and the review is complete. A phase also requires all mandatory tasks, a QA summary and human sign-off. A document being prepared does not complete Phase 0. Failed or unrun checks remain visible. Owner/date/link placeholders remain blank rather than invented.
