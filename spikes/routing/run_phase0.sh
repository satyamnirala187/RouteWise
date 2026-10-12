#!/usr/bin/env bash
# Reproduce the Phase 0 spike from a clean checkout. Requires python3.14 on PATH.
# Offline by default: uses recorded real matrices (DU North Campus local Valhalla; Bengaluru OSRM
# kept as historical evidence and not regenerated). No paid service is called.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3.14 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.lock
fi
.venv/bin/python -m pytest -q
.venv/bin/python -m routewise_spike run-scenario --matrix du-fleet      # DU North Campus, recorded local Valhalla (scooter + motorcycle)
.venv/bin/python -m routewise_spike cost-projection
.venv/bin/python -m routewise_spike google-check || echo "google-check: BLOCKED/FAILED (see evidence/google_routes_check.json)"
