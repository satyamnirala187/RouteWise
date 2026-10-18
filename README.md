# RouteWise

A mobile-first delivery-routing PWA for a small startup: Excel import → rider configuration → endpoint confirmation → road-based multi-rider routes → simple delivery updates. Scope, workflow and plans are in [`docs/source`](docs/source/START-HERE.md).

**Current state:** Phase 0 accepted for local development on 13 Oct 2026 (`2a34226`, [record](docs/phase0/OWNER-ACCEPTANCE-2026-10-13.md)). **Phase 1 (foundation, secure sign-in, Excel import) accepted for local development on 13 Oct 2026** (`fcac55e`, [record](docs/phase1/OWNER-ACCEPTANCE-2026-10-13.md), [report](docs/phase1/PHASE1-REPORT.md)). **Phase 2 (routing and multi-rider constraints) is in progress and not complete:** step 2A (rider setup and destination confirmation) is committed at `13de782`, and step 2B (local Valhalla + OR-Tools planning, versioned plans; API only) is committed locally and **awaiting review**: see the [2A report](docs/phase2/STEP-2A-REPORT.md) and [2B report](docs/phase2/STEP-2B-REPORT.md). Step 2C (screens and end-to-end verification) has not started ([plan](docs/phase2/IMPLEMENTATION-PLAN.md)). Delivery area: DU North Campus, Delhi; budget ₹0; nothing is deployed.

## Layout

```text
docs/source/        verbatim copy of the project documentation package (do not edit here)
docs/phase0/        Phase 0 report, owner acceptance, evidence (historical and accepted baseline)
docs/phase1/        Phase 1 report, owner acceptance, screenshots, evidence
docs/phase2/        Phase 2 plan and step reports (2A committed; 2B committed, awaiting review)
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
