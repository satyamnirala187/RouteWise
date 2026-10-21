# Local development (Phase 1, Phase 2 and Phase 3 steps 3A–3B)

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

Open http://localhost:5173 and sign in. Admins land on **Orders**; the menu also has **Round setup**, **Plan**, **Import** and **Office & riders**. The selected round travels in the URL (`?round=`), never in browser storage. Riders land on **My deliveries**, one round at a time (`?round=`): the destination card for that round (choose, save, then confirm), then their own deliveries in the saved route order with Call and Navigate links (3A) and their own status changes (3B).

A plan needs the local Valhalla tiles (step 2b above). Without them, Optimize reports `ROUTING_ENGINE_UNAVAILABLE`; there is no fallback.

**Production-style single origin (local check only, not a deployment):** `cd apps/web && npm run build`, then run the API alone. It serves `apps/web/dist` at http://127.0.0.1:8000. In production, set `ROUTEWISE_ENV=production`; the app then refuses to start without Secure cookies and uses the `__Host-` cookie prefix.

## Tests

```bash
cd services/api && .venv/bin/python -m pytest -q             # API: real PostgreSQL (routewise_test), migrations, mocked network
cd apps/web && npm run typecheck && npx vitest run            # frontend type checks + unit tests
E2E_SHOTS_DIR=/tmp/rw-shots scripts/e2e.sh                     # Playwright, desktop + mobile, isolated routewise_e2e DB (Phase 1 + Phase 2 specs)
ROUTEWISE_E2E_LIVE=1 E2E_SHOTS_DIR=/tmp/rw-shots scripts/e2e.sh e2e/phase2-live.spec.ts   # opt-in: browser planning on the real local tiles
python3 scripts/web_defect_check.py /tmp/rw-webmut            # optional: targeted 2C/3A/3B defect checks on a scratch copy of apps/web
cd spikes/routing && .venv/bin/python -m pytest -q            # Phase 0 routing regression
python3 services/api/tools/mutation_check.py <copy of services/api> services/api/.venv/bin/python   # optional
```

Browser tests plan with the **recorded** real local-Valhalla DU matrices: `services/api/scripts/e2e_app.py` (used only by `playwright.config.ts`) injects them through the test-only seam, and every plan shown says "Recorded real-road distances". It also offers a hold file (`.local/e2e/hold-solve`) so a test can change input while a run is in progress. `ROUTEWISE_E2E_LIVE=1` uses the real tiles instead. Without `E2E_SHOTS_DIR`, the Phase 1 spec rewrites the accepted `docs/phase1/screenshots/`; the Phase 2 spec writes to `docs/phase2/screenshots/2c/` (override with `E2E_2C_SHOTS_DIR`), the Phase 3 specs to `docs/phase3/screenshots/3a/` and `3b/` (override with `E2E_3A_SHOTS_DIR` and `E2E_3B_SHOTS_DIR`), and the Phase 4 specs to `docs/phase4/screenshots/4a/`, `4b/` and `4c/` (override with `E2E_4A_SHOTS_DIR`, `E2E_4B_SHOTS_DIR` and `E2E_4C_SHOTS_DIR`). To keep accepted screenshots untouched, point all of them at a scratch directory.

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
ROUTEWISE_LIVE_TESTS=1 .venv/bin/python -m pytest -q -m live tests/test_planning_live.py   # API planning run, a rider reroute (4B) and a grouped route (4C) on the real local tiles
.venv/bin/python tools/benchmark_planning.py                                                # local timing benchmark → docs/phase2/evidence/
```

## Rider delivery view (step 3A, read-only)

| Endpoint (rider) | Purpose |
|---|---|
| `GET /api/rider/delivery-rounds` | Rounds the rider takes part in or holds orders in, newest first, with own Pending/Postponed/Completed counts |
| `GET /api/rider/rounds/{id}/deliveries` | Own orders in that round: Pending orders in the **current** plan's stop order (`sequence`), Pending orders outside it (`unsequenced`), `postponed`, `completed`; the plan's version, `out_of_date` and own route; own start/destination by kind and depot label only. A round the rider neither takes part in nor holds orders in is a 404 |

Each order carries only name, product, contact (as stored), instructions, status and `location`, which is present only for a resolved pin inside the service area (otherwise `location_issue` says why). The web app builds `tel:` and Google Maps directions links from these in `apps/web/src/links.ts` (format: <https://developers.google.com/maps/documentation/urls/get-started#directions-action>); nothing opens without a tap, and the device location is never requested.

## Rider status updates (step 3B)

| Endpoint (rider) | Purpose |
|---|---|
| `POST /api/rider/orders/{id}/status` | Body `{"status": "Completed" \| "Postponed" \| "Pending", "expected_version": n}`. Allowed: Pending → Completed, Pending → Postponed, Postponed → Pending. Returns `{changed, order, view}` (the refreshed delivery view). Another rider's or a missing order: 404. Already that status: 200 with `changed: false` (repeats are harmless). Version differs: 409 `order_changed`. Order moved to another rider by a plan: 409 `order_reassigned`. Completed reopened or Postponed → Completed: 422 `transition_not_allowed` |

Two revisions per round (migration 0004):
- `input_version`: every planning-input change, rider progress included. It makes any in-flight solve stale.
- `route_version`: every change *except* a rider's own progress. A plan is `out_of_date` when its recorded `route_version` differs.

Plans also report `progress_since_plan` (only progress since; the remaining saved sequence is valid) and, for the current plan, `unplanned_pending` (Pending orders it does not route). Admin status edits still bump both. Details and locking: [the step 3B report](phase3/STEP-3B-REPORT.md).

## Rider reroute (step 4B API; screens since 4D)

| Endpoint (rider) | Purpose |
|---|---|
| `POST /api/rider/rounds/{id}/reroute` | Body `{"origin": {...}, "expected_plan_version": n, "expected_revision": n}`. The origin is one of `{"kind": "current_position", "lat", "lng", "accuracy_m", "age_s"}`, `{"kind": "last_completed_stop", "order_id"}` or `{"kind": "configured_start"}`. Returns 202 with a run, or a coded 404/409/422/503. Re-sequences only the rider's own Pending orders |
| `GET /api/rider/reroutes/{run_id}` | The rider's own run (another rider's: 404) |

**Effective route.** The delivery view's `plan.rider_route` is the rider's current revision of the current plan, or the plan route. `plan.route` stays the admin plan's route. The admin plan adds `rider_route` per rider.

**Versions (migration 0005).** A rider's own destination change bumps only `round_riders.route_version`, so only that rider's route shows "awaiting recalculation". A confirmation no longer invalidates the round.

**Provisional limits** (configurable): `ROUTEWISE_REROUTE_GPS_MAX_ACCURACY_M` (100), `ROUTEWISE_REROUTE_GPS_MAX_AGE_S` (60) and `ROUTEWISE_REROUTE_SOLVE_SECONDS` (10).

**Privacy.** Device positions are used in memory only, and never stored or logged.

Details: [the step 4B report](phase4/STEP-4B-REPORT.md).

## Rider screens for rerouting and shared stops (step 4D)

The rider page (`apps/web/src/pages/RiderPage.tsx`) uses only the 4B and 4C APIs above; no backend contract changed.

- **"Recalculate my route"** (`components/RerouteSection.tsx`, state in `useReroute.ts`, pure helpers in `reroute.ts`) is a section of its own between the next-customer panel and the Route card. It is always offered on demand, and cues appear after a confirmed Postpone ("Keep current order" or "Recalculate my route"), for Pending orders outside the saved route, and after a changed destination is confirmed. **Nothing is ever recalculated by itself.**
- **Origins are buttons the rider taps; none is preselected or remembered.** "Use my current location" (device position), "From my last completed stop" (only when the server offers it, labelled "not your current position") and "From the Office/Warehouse (my configured start)" (only when the server permits it, same label).
- **Location** is requested once, only after the rider taps the location button (`getCurrentPosition`, `enableHighAccuracy`, `maximumAge: 0`, 15 s; never `watchPosition`). The server's published limits (`reroute.gps_limits`) are checked in the browser before anything is sent, and again by the server. The position exists only between the read and the request: it is never kept in state, storage, the URL, a log or a message. It needs a **secure context** (HTTPS or `http://localhost`): on the Wi-Fi test address the app says "Location isn't available on this connection" and the other origins still work.
- **Run safety.** One action at a time (a synchronous lock). The request carries `expected_plan_version` and `expected_revision`. An unanswered request is an *unknown* outcome: the server state is read first (`reroute.in_progress_run_id`, then the plan version **and** revision number together, because revision numbers restart with every admin plan), the request is never resent by itself, and while the state is unresolved no new request can be started (the hook's `start` refuses, not only the buttons; dismissing the message does not lift it) and only a read-only "check again" is offered. If an admin plan replaced the one the request was made on, the screen says so and never claims the requested route is shown or the saved route unchanged. A refresh discovers the rider's own run (`in_progress_run_id`) and follows it. Polling (`planning.pollRun`, shared with the admin runs) is bounded and stops on navigation, round change, sign-out and a 401. **Success is shown only after the server confirms the run and the effective delivery view shows that revision on the same plan version.** A run found by reading the server (refresh, "already in progress") is worded conservatively, because who started it is not established. Failed, stale (inputs changed, round replanned), busy and interrupted runs are worded differently, and the previous route stays shown. Status and setup actions wait while a run is in progress; offline, recalculating is disabled (no cache, no queue).
- **Shared stops.** Each saved stop is one container (`data-testid="rider-stop"`). A stop with several customers shows its count and **one** Navigate (the server's validated stop location); each customer keeps their own Call, contact, notes and status actions. The next-customer panel follows the server's order, including a first-delivery customer leading a group. The screen never merges stops itself.
- **Route card.** Same layout; its data reads the rider's effective route: revision, origin and planned totals ("planned total for that revision, not the distance left"), and, after a destination change (including new Home/Custom coordinates under the same kind, detected through the server's `awaiting_recalculation`), that the saved route still ends at the previous destination until a recalculation succeeds.
- **Admin plan page** lists each rider's current (recalculated) route and planned totals beside the saved plan: kinds and order codes only, never a position or a private endpoint.

Browser tests label emulated GPS as **mocked geolocation**; real-device location is not tested yet. Details and the owner phone checklist: [the step 4D report](phase4/STEP-4D-REPORT.md).

## Stop groups (step 4C; admin controls and API, rider screens since 4D)

Same-building customers can share one navigation stop. **Chosen local implementation default (provisional, not an approved permanent policy):** groups are suggested only for orders of one round whose stored pins are resolved, inside the service area and **exactly identical**; nothing is grouped until an admin confirms it; nearby pins, names and address text never group anything; identical pins can stay separate stops (different entrances).

| Endpoint (admin) | Purpose |
|---|---|
| `GET /api/admin/rounds/{id}/stop-groups` | Existing groups and same-pin suggestions (order codes, statuses and versions only; no coordinates) |
| `POST /api/admin/rounds/{id}/stop-groups` | Body `{"orders": [{"id", "version"}, ...]}` makes exactly these orders one stop. All succeed or none do. 404 `NOT_IN_ROUND`; 409 `STALE_ORDERS`, `GROUP_INCOMPLETE` (an existing group would be split); 422 `LOCATION_NOT_VALID`, `PINS_DIFFER`, `GROUP_TOO_SMALL`, `DUPLICATE_ORDERS`, `GROUP_TOO_LARGE` |
| `DELETE /api/admin/orders/{id}/stop-group` | Body `{"version"}` takes one order out; a group left with one order dissolves. 409 `STALE_ORDERS`, `NOT_GROUPED` |

- **One suggestion rule** for the badges (`same_pin_as`) and the panel: a pin that is resolved, inside the service area and exactly identical, on an order that is not Completed. Orders with identical pins outside the area (or unresolved) are neither badged nor suggested. An existing group (`stop_group`) is always reported as it is, whatever the pins.
- The group id (`orders.building_id`) is generated by the server and never sent to riders. Grouping changes only `building_id` and the order's `version`; never a status, customer detail, owner lock, priority or assignment.
- A pin edit (manual pin or link) that **actually changes** the pin takes the order out of its group; the response carries `stop_group_notice` and `stop_group_freed`. Re-applying the same pin keeps the group.
- Group changes are planning input: the round's `input_version` and `route_version` move once per request, so in-flight solves (and rider reroutes) end stale and the saved plan is out of date. Saved plans and rider revisions are never edited.
- **Planning and reroutes:** a group is one stop per applicable rider; capacity counts orders; a group larger than the rider it must fit, or with different owner locks, is split (no order is moved or dropped); first-priority customers lead their stop; a rider never gets two stops at one building. A reroute groups only the rider's own Pending orders.
- **Rider API:** each stop in `GET /api/rider/rounds/{id}/deliveries` adds `customers`, `shared`, `location` and `location_issue`; customers keep their own order records and statuses. The shared-stop screens and one Navigate per stop arrived in 4D.
- **Locking:** order rows (sorted by id, one statement) then the round row; versions reject stale views. Details: `routewise_api/stop_groups.py`, [the step 4C report](phase4/STEP-4C-REPORT.md).

## Real-phone testing (Phase 3 Wi-Fi; localhost mode since 4D)

`services/api/scripts/phone_setup.py` builds the isolated `routewise_phone` database: synthetic riders and customers on public DU points, planned on the local tiles. `scripts/phone-server.sh` serves only the app on this Mac's Wi-Fi address, port 8020; PostgreSQL stays on 127.0.0.1. **`scripts/phone-server.sh localhost`** (4D) binds only to `127.0.0.1` and allows exactly `http://localhost:8020`, for a USB phone test where you run `adb reverse tcp:8020 tcp:8020` yourself; `localhost` is a secure context, so the phone can share its GPS position there, which it cannot on the plain-HTTP Wi-Fi address. `--print-config` prints the mode, host and allowed origin and starts nothing. The script never runs `adb` or touches a device. Steps, checklist and shutdown: [docs/phase3/PHONE-TEST-GUIDE.md](phase3/PHONE-TEST-GUIDE.md). Credentials and expected stops go to the git-ignored `.local/phone/`.

**Schema check (since 4B).** `scripts/phone-server.sh` first runs `services/api/scripts/phone_db.py check` (read-only) and does not start if `routewise_phone` is on an older migration than the code, printing what to do. It never resets, rebuilds or migrates. To bring an older phone database up to date **and keep its data**, run `services/api/.venv/bin/python services/api/scripts/phone_db.py upgrade` yourself; it touches only `routewise_phone`. `phone_setup.py` remains the explicit, data-deleting rebuild. See guide section A0.

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
