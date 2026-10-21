#!/usr/bin/env bash
# Phase 3 real-phone test server (local network only). See docs/phase3/PHONE-TEST-GUIDE.md.
#
#   scripts/phone-server.sh              # Wi-Fi mode: serve on this Mac's Wi-Fi address, port 8020; Ctrl+C stops it
#   scripts/phone-server.sh localhost    # localhost mode: serve on 127.0.0.1 only, for a USB phone test (below)
#   scripts/phone-server.sh [mode] --print-config   # print what it would use and exit; starts nothing
#
# Why a localhost mode (step 4D): a phone's browser shares its GPS position only with a SECURE page
# (HTTPS or http://localhost). The Wi-Fi address (plain HTTP) is not one, so location never works in Wi-Fi
# mode and the app says so. For a real GPS check, the phone reaches this Mac's loopback port over USB with
# Android's `adb reverse tcp:8020 tcp:8020` (the owner runs that; this script never runs adb, installs
# anything, enables debugging or touches a device) and opens http://localhost:8020 in Chrome.
# Localhost mode binds ONLY to 127.0.0.1 and allows exactly the origin http://localhost:<port>.
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
MODE=wifi
PRINT_CONFIG=0
usage() { echo "Usage: scripts/phone-server.sh [wifi|localhost] [--print-config]"; }
for arg in "$@"; do
  case "$arg" in
    wifi|localhost) MODE="$arg" ;;
    --print-config) PRINT_CONFIG=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg"; usage; exit 2 ;;
  esac
done
if [ "$MODE" = localhost ]; then
  HOST=127.0.0.1                      # loopback only: nothing on the network can reach it
  ORIGIN="http://localhost:$PORT"     # exactly what the phone's browser sends after `adb reverse`
else
  HOST="${PHONE_HOST:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)}"
  [ -n "$HOST" ] || { echo "No Wi-Fi address found. Connect this Mac to the same Wi-Fi as the phone."; exit 1; }
  ORIGIN="http://$HOST:$PORT"
fi
if [ "$PRINT_CONFIG" = 1 ]; then       # for tests and curiosity: nothing is started, built or opened
  echo "mode=$MODE host=$HOST port=$PORT allowed_origin=$ORIGIN"
  exit 0
fi

"$ROOT/scripts/dev-db.sh" start >/dev/null
set -a; . "$ROOT/.env"; set +a          # local secrets; never printed
export DATABASE_URL="${DATABASE_URL%/*}/routewise_phone"
export ROUTEWISE_ENV=development ROUTEWISE_COOKIE_SECURE=false ROUTEWISE_RESOLVE_SHORT_LINKS=false
export ROUTEWISE_ALLOWED_ORIGINS="$ORIGIN"

# Preflight (read-only): refuse to serve a database whose schema is older than this code, with
# instructions. It never resets, rebuilds or migrates; upgrading is the explicit `phone_db.py upgrade`.
"$ROOT/services/api/.venv/bin/python" "$ROOT/services/api/scripts/phone_db.py" check || {
  echo; echo "The server was not started."; exit 1; }

echo "Building the web app …"
(cd "$ROOT/apps/web" && npm run -s build >/dev/null)
echo
echo "RouteWise phone test server ($MODE mode)"
if [ "$MODE" = localhost ]; then
  echo "  Listening on this Mac's loopback only (127.0.0.1:$PORT)."
  echo "  On the phone (USB, after YOU run on this Mac: adb reverse tcp:$PORT tcp:$PORT):  http://localhost:$PORT"
  echo "  This is a secure page for the browser, so location can work. Nothing here runs adb for you."
else
  echo "  Open on the phone (same Wi-Fi):  http://$HOST:$PORT"
  echo "  Plain HTTP on Wi-Fi is NOT a secure page: the phone will not share its location here."
  echo "  Use 'scripts/phone-server.sh localhost' (USB) for a GPS check."
fi
echo "  Database: routewise_phone (synthetic data only). Stop with Ctrl+C."
echo "  Do not commit, paste or share this address."
echo
exec "$ROOT/services/api/.venv/bin/uvicorn" --factory routewise_api.main:get_app --app-dir "$ROOT/services/api" \
  --host "$HOST" --port "$PORT" --log-level warning --no-access-log
