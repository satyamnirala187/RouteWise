# RouteWise

A mobile-first delivery-routing PWA for a small startup: Excel import → rider configuration → endpoint confirmation → road-based multi-rider routes → simple delivery updates. Scope, workflow and plans are in [`docs/source`](docs/source/START-HERE.md).

**Current state:** Phase 0 accepted for local development on 13 Oct 2026 (`2a34226`, [record](docs/phase0/OWNER-ACCEPTANCE-2026-10-13.md)). **Phase 1 (foundation, secure sign-in, Excel import) accepted for local development on 13 Oct 2026** (`fcac55e`, [record](docs/phase1/OWNER-ACCEPTANCE-2026-10-13.md), [report](docs/phase1/PHASE1-REPORT.md)). **Phase 2 (routing and multi-rider constraints) accepted for local development on 19 Oct 2026** (`41b37f8`, [record](docs/phase2/OWNER-ACCEPTANCE-2026-10-19.md), [report](docs/phase2/PHASE2-REPORT.md)). **Phase 3 (rider screens) accepted for local development on 19 Oct 2026** ([record](docs/phase3/OWNER-ACCEPTANCE-2026-10-19.md), [report](docs/phase3/PHASE3-REPORT.md)): the rider delivery view with call and Google Maps navigation links (3A, `2b52cbc`), riders' own delivery-status updates (3B, `e2139c1`) and clearer delivery cards, with owner-reported phone results on a OnePlus Nord 5 with Chrome ([results](docs/phase3/PHONE-TEST-RESULTS.md)). **Phase 4 (quick call, rerouting, shared stops) accepted for local development on 28 Oct 2026** ([record](docs/phase4/OWNER-ACCEPTANCE-2026-10-28.md), [plan](docs/phase4/IMPLEMENTATION-PLAN.md)): the next-customer quick call ([4A](docs/phase4/STEP-4A-REPORT.md)); a rider's own rerouting ([4B](docs/phase4/STEP-4B-REPORT.md)) with the rider screens for explicit starting points and a one-shot device location that is never stored ([4D](docs/phase4/STEP-4D-REPORT.md)); and same-building stop grouping ([4C](docs/phase4/STEP-4C-REPORT.md)) with one Navigate per shared stop. Owner-reported Android phone results, including real GPS, are kept separate from the automated tests, which use mocked geolocation ([results](docs/phase4/PHONE-TEST-RESULTS.md)). The limits and grouping rule in 4B and 4C remain provisional defaults, not approved product decisions, and one early backend failure stays unidentified and unreproduced. Production readiness and Phase 5 are pending. Delivery area: DU North Campus, Delhi; budget ₹0; nothing is deployed. The source is public for review ([security policy](SECURITY.md), [security review](docs/SECURITY-REVIEW.md)); the app is not production-ready.

## Layout

```text
docs/source/        verbatim copy of the project documentation package (do not edit here)
docs/phase0/        Phase 0 report, owner acceptance, evidence (historical and accepted baseline)
docs/phase1/        Phase 1 report, owner acceptance, screenshots, evidence
docs/phase2/        Phase 2 plan, step reports and owner acceptance (accepted 19 Oct 2026 for local development)
docs/phase3/        Phase 3 step reports, evidence and screenshots (3A and 3B committed; awaiting review; Phase 3 incomplete)
docs/DEVELOPMENT.md how to run the app locally
apps/web/           React + TypeScript + Tailwind frontend (Vite)
services/api/       FastAPI backend, Alembic migrations, tests
scripts/            local PostgreSQL (dev-db.sh) and browser tests (e2e.sh)
spikes/routing/     Phase 0 routing spike (Python 3.14, OR-Tools) — not production code
spikes/valhalla/    local Valhalla build scripts (data/ is git-ignored)
tests/fixtures/     public fixtures: DU North Campus (current) and Bengaluru (historical), recorded real matrices
```

## Run it

- The app (Phase 1): see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
- The Phase 0 routing spike: `cd spikes/routing && ./run_phase0.sh` (offline; see [ENVIRONMENT.md](docs/phase0/ENVIRONMENT.md)).

## Rules

- Road data © OpenStreetMap contributors (ODbL); show this attribution wherever routes or maps appear.
- Never commit secrets, real customer data, real home addresses or provider content that the provider's terms do not let us store. Use `.env` (git-ignored); `.env.example` lists variable names only.
- Synthetic or straight-line distances are always labelled as such, and never presented as road results.
- Paid map services are activated only with the owner's explicit approval and a spending cap.
