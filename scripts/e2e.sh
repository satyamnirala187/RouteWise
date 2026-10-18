#!/usr/bin/env bash
# Browser end-to-end tests (Playwright) against an isolated database (routewise_e2e).
# Offline: short-link checks are disabled; all data is synthetic. Phase 1 screenshots go to
# docs/phase1/screenshots/ unless E2E_SHOTS_DIR points elsewhere; the Phase 2 (2C) spec writes to
# E2E_2C_SHOTS_DIR (default docs/phase2/screenshots/2c/). Planning uses recorded real-road DU
# matrices unless ROUTEWISE_E2E_LIVE=1 (real local Valhalla tiles; see e2e/phase2-live.spec.ts).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rm -f "$ROOT/.local/e2e/hold-solve"
"$ROOT/scripts/dev-db.sh" start >/dev/null
"$ROOT/scripts/dev-db.sh" create-db routewise_e2e >/dev/null
E2E_STATE="$("$ROOT/services/api/.venv/bin/python" "$ROOT/services/api/scripts/e2e_setup.py")"
export E2E_STATE
E2E_DATABASE_URL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["database_url"])' "$E2E_STATE")"
export E2E_DATABASE_URL
cd "$ROOT/apps/web"
npx playwright test "$@"
