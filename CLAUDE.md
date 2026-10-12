# RouteWise — notes for Claude Code

- Scope baseline: `docs/source/notion/RouteWise/01-Product.md` (R01–R24, add-ons 2/4/8/9 only). Do not add fuel analytics, a postponed dashboard, a balanced-workload mode, or compulsory package/dispatch confirmation. Order statuses are exactly Pending / Postponed / Completed.
- Work phase by phase (`docs/source/notion/RouteWise/04-Roadmap.md`). Phase 0 is in review; **do not start Phase 1 until the owner signs off** on `docs/phase0/PHASE0-REPORT.md`.
- `docs/source/` is a verbatim copy of the documentation package. Put new or changed docs in `docs/phase0/` (and later phase folders), not in `docs/source/`.
- Spike: `cd spikes/routing && ./run_phase0.sh`. Tests: `.venv/bin/python -m pytest -q`. Live network tests are opt-in via `ROUTEWISE_LIVE_TESTS=1`.
- Python 3.14.3 in `spikes/routing/.venv` (pinned by `requirements.lock`). Never modify system Python.
- Never label synthetic or straight-line costs as road distances; a missing matrix edge is never zero. Every matrix carries provenance (`real_road`, `recorded`).
- No secrets or real customer data in Git, fixtures, logs or docs. Google Routes calls need explicit owner approval (`google-check --allow-billing`).
- Notion is updated by a human after approval; `docs/phase0/NOTION-UPDATE-PROPOSAL.md` is a proposal only.
- Owner constraints (2026-10-12): delivery area DU North Campus, Delhi; routing/service budget ₹0; no paid subscriptions or billable services. Stadia and Google stay optional and inactive; never depend on public demo servers for production.
- Local routing: self-hosted Valhalla (`spikes/valhalla/build_tiles.sh`, `.venv-valhalla`). Bengaluru fixtures/evidence are historical only — do not edit them.
