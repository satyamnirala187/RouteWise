#!/usr/bin/env bash
# Browser end-to-end tests (Playwright) against an isolated database (routewise_e2e).
# Offline: short-link checks are disabled; all data is synthetic. Screenshots go to docs/phase1/screenshots/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/dev-db.sh" start >/dev/null
"$ROOT/scripts/dev-db.sh" create-db routewise_e2e >/dev/null
E2E_STATE="$("$ROOT/services/api/.venv/bin/python" "$ROOT/services/api/scripts/e2e_setup.py")"
export E2E_STATE
E2E_DATABASE_URL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["database_url"])' "$E2E_STATE")"
export E2E_DATABASE_URL
cd "$ROOT/apps/web"
npx playwright test "$@"
