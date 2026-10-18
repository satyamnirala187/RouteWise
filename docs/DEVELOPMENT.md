# Local development (Phase 1 and Phase 2 steps 2A–2C)

Everything runs on this Mac, at ₹0, with no admin rights, Docker or Homebrew. Secrets live only in the git-ignored `.env` at the repo root.

## Prerequisites (checked 13 Oct 2026)

| Tool | Version | How it is provided |
|---|---|---|
| Python | 3.14.3 (python.org build) | Already installed; each service has its own venv |
| Node / npm | 24.18.1 / 11.16.0 | Already installed (nvm) |
| PostgreSQL | 18.6 | `scripts/dev-db.sh install` downloads EDB's official macOS binaries zip into `.local/`. It verifies the SHA-256 and the Apple code signature (Developer ID: EnterpriseDB Corporation) |
| Chromium for browser tests | Playwright 1.63 headless shell | `npx playwright install chromium` (into `~/Library/Caches/ms-playwright`) |

## First-time setup

```bash
# 1. Database: local cluster on 127.0.0.1:54329; writes credentials to .env (chmod 600)
scripts/dev-db.sh install
scripts/dev-db.sh init

# 2. API
cd services/api
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock   # includes ortools 9.15.6755 and pyvalhalla 3.9.1 (2B)
.venv/bin/alembic upgrade head

# 2b. Local road routing (2B). Planning uses in-process Valhalla on locally built OpenStreetMap
#     tiles; there is no fallback. Build them once (this needs spikes/routing/.venv-valhalla; see
#     docs/phase0/VALHALLA-LOCAL.md); the API reads spikes/valhalla/data/valhalla_tiles by default.
../../spikes/valhalla/build_tiles.sh            # or set ROUTEWISE_VALHALLA_TILES=/path/to/valhalla_tiles

# 3. Users. No public sign-up: create accounts locally. The password is typed at a hidden prompt
#    (or piped on stdin), never passed as an argument, never committed.
.venv/bin/python -m routewise_api.cli create-user --username admin1 --role admin
.venv/bin/python -m routewise_api.cli create-user --username rider1 --role rider --name "Rider One" --vehicle scooter
#    later: set-password --username rider1 | deactivate --username rider1   (both end existing sessions;
#    deactivate also marks the plans of every round the rider participates in out of date)

# 4. Web
cd ../../apps/web
npm ci
```

## Run (two terminals)

```bash
scripts/dev-db.sh start                     # if not already running

cd services/api && .venv/bin/uvicorn --factory routewise_api.main:get_app --host 127.0.0.1 --port 8000 --reload
cd apps/web && npx vite                     # http://localhost:5173 (proxies /api to :8000)
```

Open http://localhost:5173 and sign in. Admins land on **Orders**; the menu also has **Round setup**, **Plan**, **Import** and **Office & riders**. The selected round travels in the URL (`?round=`), never in browser storage. Riders land on their page: **My rounds** (choose, save, then confirm a destination for each round they take part in) and **My deliveries**.

A plan needs the local Valhalla tiles (step 2b above). Without them, Optimize reports `ROUTING_ENGINE_UNAVAILABLE`; there is no fallback.

**Production-style single origin (local check only, not a deployment):** `cd apps/web && npm run build`, then run the API alone. It serves `apps/web/dist` at http://127.0.0.1:8000. In production, set `ROUTEWISE_ENV=production`; the app then refuses to start without Secure cookies and uses the `__Host-` cookie prefix.

## Tests

```bash
cd services/api && .venv/bin/python -m pytest -q             # API: real PostgreSQL (routewise_test), migrations, mocked network
cd apps/web && npm run typecheck && npx vitest run            # frontend type checks + unit tests
E2E_SHOTS_DIR=/tmp/rw-shots scripts/e2e.sh                     # Playwright, desktop + mobile, isolated routewise_e2e DB (Phase 1 + Phase 2 specs)
ROUTEWISE_E2E_LIVE=1 E2E_SHOTS_DIR=/tmp/rw-shots scripts/e2e.sh e2e/phase2-live.spec.ts   # opt-in: browser planning on the real local tiles
python3 scripts/web_defect_check.py /tmp/rw-webmut            # optional: targeted 2C defect checks on a scratch copy of apps/web
cd spikes/routing && .venv/bin/python -m pytest -q            # Phase 0 routing regression
python3 services/api/tools/mutation_check.py <copy of services/api> services/api/.venv/bin/python   # optional
```

Browser tests plan with the **recorded** real local-Valhalla DU matrices: `services/api/scripts/e2e_app.py` (used only by `playwright.config.ts`) injects them through the test-only seam, and every plan shown says "Recorded real-road distances". It also offers a hold file (`.local/e2e/hold-solve`) so a test can change input while a run is in progress. `ROUTEWISE_E2E_LIVE=1` uses the real tiles instead. Without `E2E_SHOTS_DIR`, the Phase 1 spec rewrites the accepted `docs/phase1/screenshots/`; the Phase 2 spec writes to `docs/phase2/screenshots/2c/` (override with `E2E_2C_SHOTS_DIR`).

The mutation check rewrites files, so run it on a copy laid out as `<dir>/services/api`, with `<dir>/.env` and `<dir>/tests/fixtures` linked to the real ones: the code finds both relative to the package. It uses the same test database, so don't run the API suite at the same time.

## Rider setup (step 2A API; screens since 2C)

Every mutation needs the session's CSRF token.

| Who | Endpoint | Purpose |
|---|---|---|
| Admin | `GET /api/admin/depots`, `PUT /api/admin/depots/{office\|warehouse}` | Office and Warehouse: label and coordinates inside the DU North Campus area. Send `version: null` to create, else the version being edited |
| Admin | `GET /api/admin/riders`, `PATCH /api/admin/riders/{id}` | Rider profiles: display name, default vehicle. Accounts are still created with the CLI |
| Admin | `GET /api/admin/rounds/{id}/riders`, `PUT /api/admin/rounds/{id}/riders/{rider_id}` | Add a rider to a round (`version: null`), or change participation, vehicle (`scooter`/`bike`), capacity (1–1000 orders) and start (`office`/`warehouse`) |
| Admin | `GET /api/admin/rounds/{id}/readiness` | Order-pin blockers (`blockers`) plus rider-setup blockers (`configuration_blockers`); since 2C also `mode`, `pending_orders` and `planning_limits`. Never destination coordinates |
| Rider | `GET /api/rider/rounds`, `GET /api/rider/rounds/{id}` | Own rounds and own setup, including `config_version` |
| Rider | `PUT /api/rider/rounds/{id}/destination` | Choose `office`, `warehouse`, `home`, `last_stop` or `custom` (Home/Custom need `lat`/`lng`) |
| Rider | `POST /api/rider/rounds/{id}/confirm` | Confirm `{"config_version": n}`, the version shown; a changed setup returns 409 |

The confirmation rules are in `services/api/routewise_api/riders.py` and [the step 2A report](phase2/STEP-2A-REPORT.md).

## Planning (step 2B API; screens since 2C)

| Endpoint (admin) | Purpose |
|---|---|
| `PUT /api/admin/rounds/{id}/mode` | `equal`, `smart` (default) or `manual` |
| `PUT /api/admin/orders/{id}/lock`, `POST /api/admin/rounds/{id}/locks` | Owner lock for one order, or all-or-nothing for many (manual assignment); `rider_id: null` clears |
| `PUT /api/admin/orders/{id}/priority` | First delivery (Pending orders only) |
| `POST /api/admin/rounds/{id}/optimize` | Validate, snapshot and queue a run → 202 with the run; coded 409/422/503 otherwise |
| `GET /api/admin/planning-runs/{run_id}`, `GET /api/admin/rounds/{id}/planning-runs` | Run state, error code/details, timings |
| `GET /api/admin/rounds/{id}/plan`, `…/plans`, `…/plans/{version}` | Current plan (with `out_of_date`), history, a past version |

Local limits per run (`PlanningLimits` in `config.py`): 80 Pending orders, 8 riders, 100 road points, 30 s per solver strategy, 1 worker and 4 queued runs per API process. Run one API process per database: unfinished runs are marked `interrupted` when a process starts.

```bash
cd services/api
ROUTEWISE_LIVE_TESTS=1 .venv/bin/python -m pytest -q -m live tests/test_planning_live.py   # API planning run on the real local tiles
.venv/bin/python tools/benchmark_planning.py                                                # local timing benchmark → docs/phase2/evidence/
```

## Database

- Migrations: `services/api/migrations/versions/` (Alembic).
  - Apply: `alembic upgrade head`.
  - Roll back: `alembic downgrade -1`.
  - New migration: `alembic revision --autogenerate -m "..."`, then review it by hand.
- Shell: `scripts/dev-db.sh psql` (uses the superuser password from `.env`).
- Stop: `scripts/dev-db.sh stop`.
- Remove everything: stop, then delete `.local/`. Databases, binaries and e2e state live there.
- PostgreSQL never logs SQL text (`log_statement = none`), because statements can contain customer data.

## Limits enforced on import

| Limit | Value |
|---|---|
| File | `.xlsx` only, ≤ 2 MB (request body hard cap 3 MB) |
| Orders per file | ≤ 1,000 |
| Columns read | ≤ 30 |
| Header search | first 10 rows |
| ZIP container | ≤ 500 parts, ≤ 25 MB uncompressed, ≤ 100:1 compression per part |
| Rejected outright | Macros; legacy `.xls`; CSV |
| Formulas | Never evaluated (a formula cell is a row error) |
| XML parsing | Through `defusedxml` |
| Field lengths | Name 200, Product 500, Contact 40, Location 2,048, Instructions 1,000 characters |
| Short links resolved per import | ≤ 100 links, ≤ 30 s in total for all link checks (DNS, connects, reads and redirects included); the rest are marked for a manual pin |
| One short-link check (location edit) | ≤ 10 s total; per hop: DNS ≤ 3 s, connect + TLS ≤ 5 s, read ≤ 5 s, ≤ 8 s per hop; ≤ 4 redirects; headers ≤ 16 KB |
| DNS lookups | On a 4-thread pool, so stuck system lookups can't pile up |
| Concurrent imports | ≤ 2 at once (a third gets HTTP 429). Import parsing and link checks run on worker threads, never on the server's event loop |
| Preview lifetime | 1 hour |
