# RouteWise

A mobile-first delivery-routing PWA for a small startup: Excel import → rider configuration → endpoint confirmation → road-based multi-rider routes → simple delivery updates. Scope, workflow and plans are in [`docs/source`](docs/source/START-HERE.md).

**Current state:** Phase 0 accepted for local development on 13 Oct 2026 (`2a34226`, [record](docs/phase0/OWNER-ACCEPTANCE-2026-10-13.md)). **Phase 1 (foundation, secure sign-in, Excel import) accepted for local development on 13 Oct 2026** (`fcac55e`, [record](docs/phase1/OWNER-ACCEPTANCE-2026-10-13.md), [report](docs/phase1/PHASE1-REPORT.md)). **Phase 2 (routing and multi-rider constraints) accepted for local development on 19 Oct 2026** (`41b37f8`, [record](docs/phase2/OWNER-ACCEPTANCE-2026-10-19.md), [report](docs/phase2/PHASE2-REPORT.md)). **Phase 3 (rider screens) is in progress:** step 3A, the rider's read-only delivery view with call and Google Maps navigation links, is committed (`2b52cbc`, [3A report](docs/phase3/STEP-3A-REPORT.md)); step 3B, riders' own delivery-status updates, is committed ([3B report](docs/phase3/STEP-3B-REPORT.md)). Both await owner review; real-phone dialer and navigation checks have not been done, and Phase 3 is not accepted. Delivery area: DU North Campus, Delhi; budget ₹0; nothing is deployed.

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
