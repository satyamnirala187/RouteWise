#!/usr/bin/env bash
# Phase 3 real-phone test server (local network only). See docs/phase3/PHONE-TEST-GUIDE.md.
#
#   scripts/phone-server.sh          # serve on this Mac's Wi-Fi address, port 8020; Ctrl+C stops it
#
# Serves ONLY the RouteWise app (API + built web pages, one origin) against the isolated
# database routewise_phone (create it with services/api/scripts/phone_setup.py; bring an older one
# up to date, keeping its data, with services/api/scripts/phone_db.py upgrade). It checks the schema
# first and does not start if the database is out of date. PostgreSQL stays bound to 127.0.0.1;
# the app listens on the Wi-Fi address only. No tunnel, no router change.
# Plain HTTP on a trusted Wi-Fi: cookies are not marked Secure, so use this only for the test.
# The address is printed here and never written to a file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PHONE_PORT:-8020}"
HOST="${PHONE_HOST:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)}"
[ -n "$HOST" ] || { echo "No Wi-Fi address found. Connect this Mac to the same Wi-Fi as the phone."; exit 1; }

"$ROOT/scripts/dev-db.sh" start >/dev/null
set -a; . "$ROOT/.env"; set +a          # local secrets; never printed
export DATABASE_URL="${DATABASE_URL%/*}/routewise_phone"
export ROUTEWISE_ENV=development ROUTEWISE_COOKIE_SECURE=false ROUTEWISE_RESOLVE_SHORT_LINKS=false
export ROUTEWISE_ALLOWED_ORIGINS="http://$HOST:$PORT"

# Preflight (read-only): refuse to serve a database whose schema is older than this code, with
# instructions. It never resets, rebuilds or migrates; upgrading is the explicit `phone_db.py upgrade`.
"$ROOT/services/api/.venv/bin/python" "$ROOT/services/api/scripts/phone_db.py" check || {
  echo; echo "The server was not started."; exit 1; }

echo "Building the web app …"
(cd "$ROOT/apps/web" && npm run -s build >/dev/null)
echo
echo "RouteWise phone test server"
echo "  Open on the phone (same Wi-Fi):  http://$HOST:$PORT"
echo "  Database: routewise_phone (synthetic data only). Stop with Ctrl+C."
echo "  Do not commit, paste or share this address."
echo
exec "$ROOT/services/api/.venv/bin/uvicorn" --factory routewise_api.main:get_app --app-dir "$ROOT/services/api" \
  --host "$HOST" --port "$PORT" --log-level warning --no-access-log
