# RouteWise

A mobile-first delivery-routing PWA for a small startup: Excel import → rider configuration → endpoint confirmation → road-based multi-rider routes → simple delivery updates. Scope, workflow and plans are in [`docs/source`](docs/source/START-HERE.md).

**Current state: Phase 0 (discovery and routing spike) is in review and not complete.** The live trial with the selected two-wheeler provider is blocked, and owner sign-off is pending. No application (Phase 1+) exists yet. See the [Phase 0 report](docs/phase0/PHASE0-REPORT.md).

## Layout

```text
docs/source/        verbatim copy of the project documentation package (do not edit here)
docs/phase0/        Phase 0 report, acceptance results, provider evaluation, ADR, offline/privacy proposal, Notion proposal
spikes/routing/     Phase 0 routing spike (Python 3.14, OR-Tools) — not production code
tests/fixtures/     public/synthetic fixtures and the recorded real OSRM matrix
```

## Run the Phase 0 spike

```bash
cd spikes/routing
./run_phase0.sh     # needs python3.14; offline; no paid service is called
```

See [docs/phase0/ENVIRONMENT.md](docs/phase0/ENVIRONMENT.md) for individual commands, live checks and versions.

## Rules

- Never commit secrets, real customer data, real home addresses or provider content that the provider's terms do not let us store. Use `.env` (git-ignored); `.env.example` lists variable names only.
- Synthetic or straight-line distances are always labelled as such, and never presented as road results.
- Paid map services are activated only with the owner's explicit approval and a spending cap.
