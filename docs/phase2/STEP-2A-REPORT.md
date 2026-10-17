# Step 2A report: riders, depots, rider-confirmed destinations, readiness

**Date:** 17 October 2026 · **Prepared by:** Claude Code · **Status: implemented locally; awaiting owner review.** Phase 2 is not complete: steps 2B (optimizer) and 2C (screens) have not started. Nothing is deployed or pushed; ₹0 spent; Notion not accessed.

**Base:** commit `fcac55e` (Phase 1, accepted 13 Oct 2026). **Revision:** the 2A work, the Phase 1 acceptance copy and the Phase 2 plan are recorded in one local commit, *"Add RouteWise rider setup and destination confirmation"*, the commit directly after `fcac55e` (see `git log`). It has not been pushed. **Scope:** backend/API only, per [the plan](IMPLEMENTATION-PLAN.md) §3 and the owner's 2A instructions. No OR-Tools or Valhalla integration, plans, rerouting, grouping, offline work, configuration screens or new dependencies.

## 1. What was implemented

**Office and Warehouse** (`depots` table, one row each)
- The admin creates or edits each one: label plus coordinates.
- Coordinates must be finite, in range, not 0,0, and inside the DU North Campus service area (the Phase 0 routing-graph box). Anything else is a 422.
- Versioned: creating requires `version: null`, editing requires the current version, and a stale edit is a 409.
- Nothing is seeded, so no business location is stored in Git. Tests use the public OSM fixture, whose Office/Warehouse roles are labelled synthetic.

**Rider management**
- The admin lists rider profiles (username, display name, default vehicle, whether the account is active) and edits the display name and default vehicle, with version checks.
- Creating and deactivating accounts stays in the CLI.

**Per-round rider setup** (`round_riders`)
- The admin adds a rider to a round or edits their setup:
  - participation on or off;
  - vehicle `scooter` or `bike` (defaults from the profile, and is required if the profile has none);
  - capacity, a strict integer from 1 to 1000 orders (1000 is the import limit);
  - start `office` or `warehouse`.
- A deactivated account can't be added or re-added.
- Removing a rider sets `participating = false`. That rider then no longer counts for readiness and can't reach the round through the rider API.

**Rider destinations** (`rider_endpoints`)
- The signed-in rider chooses Office, Warehouse, Home, Last stop or Custom for each round they take part in.
- Home and Custom need validated coordinates inside the service area. The other three must not carry coordinates. The database enforces this as well as the API.
- Last stop is stored without coordinates and shown to the rider as an open route.
- Rider paths contain no rider id; the session decides whose setup is read or written. Another rider's round, or one the rider doesn't take part in, returns the same 404 as a missing one.

**Confirmation**
- The rider confirms with `POST /api/rider/rounds/{id}/confirm` and `{"config_version": n}`, the version they were shown.
- A stale version gets `409 {"code": "configuration_changed", "message": …, "current_version": …}`.
- An incomplete setup (missing depot, no destination, invalid location) gets `422 {"code": "configuration_incomplete", "issues": […]}`.
- There's no admin route that selects or confirms a destination, and admins get 403 on every rider route. Confirmation-like fields sent to the admin setup endpoint are ignored.

**Privacy**
- Admin responses carry only the destination **kind**, never Home/Custom coordinates. This covers the round-rider list, readiness, depots, rider profiles, order and round lists, and the responses to edits.
- The coordinates stay in `rider_endpoints` for the future planner and are returned only to the rider who chose them.
- Readiness reasons name riders and kinds only.

**Readiness** (`GET /api/admin/rounds/{id}/readiness`, extended)
- Phase 1 fields keep their meaning: `orders`, and `blockers` (the order-location blockers, unchanged).
- New fields:
  - `orders_ready`;
  - `configuration_blockers`, each with `code`, `reason` and, where relevant, `rider_id`/`rider`;
  - `riders`: participating and confirmed counts;
  - `input_version`.
- `ready` is true only if orders are ready **and** no configuration blocker remains.
- Configuration blocker codes:

| Code | Meaning |
|---|---|
| `no_participating_riders` | The round has no participating rider |
| `account_inactive` | The rider's account is deactivated |
| `start_depot_missing` / `start_depot_outside_area` | The start depot has no location, or it is outside the service area |
| `destination_missing` | The rider has not chosen a destination |
| `destination_depot_missing` / `destination_depot_outside_area` | The depot chosen as destination has no location, or it is outside the service area |
| `destination_invalid` | The Home/Custom location is not valid in the service area |
| `not_confirmed` | The rider has never confirmed |
| `confirmation_outdated` | The setup changed after the rider confirmed |

- `orders.planning_input()` is unchanged and still the only path from orders to a future optimizer.

**Frontend contract** (shared type only, no new screens)
- `apps/web/src/api.ts` has the new `Readiness` fields.
- The Orders page bases its pin message on `orders_ready`, keeping the Phase 1 wording, and adds one sentence when rider setup is still incomplete. Without this, the existing message would have claimed orders need pins when only rider setup was blocking.

## 2. Exact confirmation and version rules

Each (round, rider) has a `config_version`. A confirmation stores `confirmed_version` and `confirmed_at`. **A rider is confirmed only while `confirmed_version == config_version`**, so a version bump invalidates the confirmation without anything having to clear it. The database enforces `confirmed_version ≤ config_version` and that version and time are set together.

| Accepted change | Rider's `config_version` | Round `input_version` |
|---|---|---|
| Admin adds a rider to the round | starts at 1, not confirmed | +1 |
| Admin changes **vehicle, capacity or start** | +1 for that rider only | +1 |
| Admin turns participation **off** or **on** again | +1 (re-adding needs a new confirmation) | +1 |
| Rider chooses a **different destination kind or Home/Custom coordinates** | +1 | +1 |
| Admin moves the **coordinates of a depot** the rider's start or destination uses | +1 for each such rider, in every round | +1 once per affected round |
| Rider confirms the current version | confirmation becomes current | +1 |
| Order **pin or status** changes (manual pin, link, status) | unchanged: **no reconfirmation** | +1 |
| A write that changes nothing (same values, same destination, repeated confirmation, same pin) | unchanged | unchanged |
| Depot **label** only; rider **profile** (name, default vehicle); **customer text** (name, product, contact, instructions) | unchanged | unchanged |

**Concurrency.** Every configuration write and every confirmation takes locks in one order:
1. both depot rows, `FOR SHARE` (a depot edit takes its own row `FOR UPDATE`);
2. the round row, `FOR UPDATE`;
3. the round-rider row, `FOR UPDATE`.

The confirmation compares versions under these locks. A concurrent change therefore either commits first, and the confirmation gets a 409, or commits after, and its version bump invalidates the confirmation that just landed. Order edits lock the order and then update the round row; they never take depot or round-rider locks, so no cycle exists.

**Not implemented, on purpose:** the plan's Q1 proposal, which would allow re-planning only while all orders are Pending. Q1–Q8 in the plan are now marked as pending proposals, not approved decisions. No order-status rule was added, and Phase 1 behaviour is unchanged apart from the readiness extension.

## 3. Schema (migration `0002`)

| Object | Details |
|---|---|
| `depots` (new) | PK `kind` CHECK office/warehouse; `label` (non-blank CHECK); `lat`/`lng` NOT NULL with range CHECKs; `version` ≥ 1; `updated_by` → users; `updated_at` |
| `round_riders` (new) | PK (`round_id` → rounds CASCADE, `rider_id` → riders RESTRICT); index on `rider_id`; `participating`; `vehicle` CHECK scooter/bike; `capacity` CHECK 1–1000; `start_kind` CHECK office/warehouse; `config_version` ≥ 1; `confirmed_version`/`confirmed_at`, set together and ≤ `config_version` |
| `rider_endpoints` (new) | PK and composite FK (`round_id`, `rider_id`) → round_riders CASCADE; `kind` CHECK of the five; coordinates present **iff** Home/Custom; lat/lng set together; source present iff coordinates; range CHECKs |
| `delivery_rounds.input_version` (new) | NOT NULL DEFAULT 1, CHECK ≥ 1 |
| `riders.version` (new) | NOT NULL DEFAULT 1 |

`downgrade` removes exactly these objects. A test upgrades a database holding Phase 1 data (existing rows get version 1), downgrades it to `0001` and checks that the Phase 1 rows survive.

## 4. Endpoints added

| Method and path | Role | Purpose |
|---|---|---|
| `GET /api/admin/depots` · `PUT /api/admin/depots/{office\|warehouse}` | admin | Office and Warehouse |
| `GET /api/admin/riders` · `PATCH /api/admin/riders/{rider_id}` | admin | Rider profiles |
| `GET /api/admin/rounds/{round_id}/riders` · `PUT /api/admin/rounds/{round_id}/riders/{rider_id}` | admin | Round setup, confirmation state and issues (no coordinates) |
| `GET /api/admin/rounds/{round_id}/readiness` (extended) | admin | Order and configuration blockers |
| `GET /api/rider/rounds` · `GET /api/rider/rounds/{round_id}` | rider | Own rounds and full own setup with `config_version` |
| `PUT /api/rider/rounds/{round_id}/destination` | rider | Choose a destination |
| `POST /api/rider/rounds/{round_id}/confirm` | rider | Confirm the version shown |

All of them use `require_admin` or `require_rider`, and every mutation needs the session CSRF token and an allowed Origin.

## 5. Test results (run 17 Oct 2026 on this Mac)

All the results below come from runs on 17 October 2026. Raw outputs are in [`evidence/`](evidence/).

### Completed checks

| Check | Command | Result |
|---|---|---|
| API suite (real PostgreSQL `routewise_test`, migrations, mocked network) | `cd services/api && .venv/bin/python -m pytest -q` | **231 passed** (Phase 1 had 150; 81 new) |
| — 2A behaviour: depots, profiles, round setup, all 5 destinations, both starts, invalid capacities/vehicles/starts/coordinates (incl. NaN, 0,0, out of area), deactivated accounts, DB constraints, isolation, admin cannot choose/confirm, invalidation rules, idempotence, readiness gates, no coordinate leakage in admin responses or logs | `tests/test_round_setup.py` | 70 passed (included above) |
| — concurrency on real PostgreSQL: admin edit vs confirm (capacity, vehicle, start); depot move vs confirm; destination change on a second device vs confirm; two admins editing or adding the same rider; a mixed storm of depot moves, admin edits, destination changes, confirmations and pin edits with no deadlock (no 500) | `tests/test_round_concurrency.py` | 8 passed (included above); also passed 3 times in a row during development |
| — CSRF on every rider mutation (missing, wrong, other session's token, cross-origin); 2A route inventory; destination/confirm writes exist only under `/api/rider/` | `tests/test_permissions.py` | included above |
| — migration `0002`: upgrade, downgrade, upgrade; no model/schema diff; upgrade over existing Phase 1 data and downgrade back to `0001` keeping it | `tests/test_migrations_privacy.py` | included above |
| Phase 0 routing regression (unchanged) | `cd spikes/routing && .venv/bin/python -m pytest -q` | **264 passed, 5 skipped** (same as the accepted baseline) |
| Local Valhalla live checks (local tiles, no network) | `cd spikes/routing && ROUTEWISE_LIVE_TESTS=1 .venv-valhalla/bin/python -m pytest -q -m live tests/test_valhalla_du.py` | **2 passed** |
| Frontend type checks | `cd apps/web && npm run typecheck` | **OK** (exit 0) |
| Frontend unit tests | `cd apps/web && npx vitest run` | **5 passed** |
| Frontend production build | `cd apps/web && npm run build` | **OK** |
| Browser tests (Chromium; desktop 1280×800 and mobile 390×844), the existing Phase 1 spec against the extended readiness gate | `E2E_SHOTS_DIR="$PWD/docs/phase2/screenshots" scripts/e2e.sh` | **8 passed**. Screenshots saved to `docs/phase2/screenshots/` and inspected; the readiness banner keeps the Phase 1 wording and adds "Rider setup: 1 item(s) to finish before planning." The 10 accepted Phase 1 screenshots were checksummed before and after: all byte-identical |
| Defect injection (43 mutants: 25 from Phase 1, 18 new for 2A) | `tools/mutation_check.py` on a scratch copy laid out as `<dir>/services/api` (see `docs/DEVELOPMENT.md`) | Full run: **42/43 killed**. Survivor: *removed rider still reaches round*. A removed rider could still choose a destination or confirm, because the test checked only the read endpoint after removal. Added assertions that destination and confirm return 404 after removal; that mutant was then **re-run alone and killed**. All 43 were not re-run together after the fix |

### Tests changed rather than added

- `test_orders.py::test_readiness_gate_blocks_until_every_pin_is_valid` previously compared the whole readiness body and expected `ready: true` once the pins were fixed. It still asserts the exact order-location blockers. It now also asserts `orders_ready: true` after the fix, and that planning stays blocked with `no_participating_riders`. That is the intended 2A gate, not a weaker check.
- `conftest.py` truncates the new tables. `test_migrations_privacy.py` expects the new tables and head `0002`.
- `e2e/phase1.spec.ts`: the screenshot folder can be overridden with `E2E_SHOTS_DIR`. The default is unchanged, and no assertion changed.

### Not performed

- No 2A screens exist (2C), so there is no browser test of rider setup, destination choice or confirmation. These are covered by API tests only.
- A single re-run of all 43 mutants after the test fix (see above).
- Real phones, Safari/Firefox, accessibility audit, CI (no remote), production deployment, load testing.
- Planning against real roads for 2A data: there is no optimizer yet (2B).

### Locking and invalidation review

I checked the order of every lock site against the rule in §2:
- Rider setup writes, destination writes and confirmations take depots `FOR SHARE`, then the round, then the round-rider row.
- A depot edit takes its own row `FOR UPDATE`, then the affected rounds in sorted order, then the round-rider rows. It holds the depot lock throughout, so the set of affected riders cannot change mid-edit.
- Order edits lock the order and then update the round row. They never wait on a depot or round-rider lock.

No cycle exists, and the mixed-storm test ran without deadlock. The race tests confirm that after any interleaving of a change and a confirmation, the surviving confirmation is never current for a superseded version.

## 6. Limitations and remaining work

1. **API only.** There are no admin or rider screens for the 2A setup; they are planned for 2C. Today the endpoints are exercised by tests, not by a browser flow.
2. **Home/Custom take coordinates only.** There is no Google Maps link input for destinations yet. Depots likewise take coordinates only.
3. **No optimizer or plans (2B).** `input_version` is maintained and exposed, but nothing consumes it yet.
4. **Depots are global**, not per round. Moving a depot invalidates every confirmation, in every round, that uses it. There is no round "closed" state to exclude past rounds.
5. **Retention (D10)** is still not implemented. `rider_endpoints` adds rider Home coordinates to what a future purge must cover. A removed rider's destination row is kept, and is still never shown to admins.
6. **Readiness is computed on request.** It is not stored. 2B must recheck it inside the planning transaction.
7. **Carried over from Phase 1:** no CI, no real-device or Safari/Firefox testing, no live short-link test, no production deployment.
8. **Pending decisions:** Q1–Q8 and B1–B5 in the plan. In particular B1: the real Office/Warehouse locations must be entered by the owner in the local app and must never be committed.

## 7. Changed files and Git state

**Git:** branch `main`. Everything below is in the single local commit *"Add RouteWise rider setup and destination confirmation"* on top of `fcac55e`. Nothing pushed or deployed; no remote exists.

**New files:**
- `services/api/migrations/versions/0002_phase2a_riders_destinations.py`
- `services/api/routewise_api/riders.py`
- `services/api/routewise_api/routers/admin_riders.py`
- `services/api/tests/test_round_setup.py`
- `services/api/tests/test_round_concurrency.py`
- `docs/phase2/STEP-2A-REPORT.md` (this file)
- `docs/phase2/evidence/`: `api_pytest.txt`, `api_mutation_check.txt`, `phase0_regression.txt`, `web_typecheck.txt`, `web_vitest.txt`, `web_build.txt`, `e2e_playwright.txt`
- `docs/phase2/screenshots/`: 10 synthetic-data screenshots from the compatibility run

**Modified:**
- API: `routewise_api/models.py`, `routewise_api/main.py`, `routewise_api/routers/admin.py` (readiness; pin and status changes advance `input_version`), `routewise_api/routers/rider.py`
- API tests and tools: `tests/conftest.py`, `tests/test_orders.py`, `tests/test_permissions.py`, `tests/test_migrations_privacy.py`, `tools/mutation_check.py` (18 new mutants; the new router added to the commit-scope mutant)
- Web: `apps/web/src/api.ts` (`Readiness` type), `apps/web/src/pages/OrdersPage.tsx` (readiness message), `apps/web/e2e/phase1.spec.ts` (screenshot folder override only)
- Docs: `README.md`, `CLAUDE.md`, `docs/README.md`, `docs/DEVELOPMENT.md` (2A endpoints, mutation-check layout, `E2E_SHOTS_DIR`), `docs/phase2/IMPLEMENTATION-PLAN.md` (status; differences from the plan; Q1–Q8 marked pending; Q1 not to be built without approval)
- From the earlier planning step, in the same commit: `docs/phase1/OWNER-ACCEPTANCE-2026-10-13.md` (verbatim copy), `docs/phase1/PHASE1-REPORT.md` (banner only), `docs/phase2/IMPLEMENTATION-PLAN.md`

**Not modified:** `docs/source/`, `spikes/`, `tests/fixtures/`, Phase 0 and Phase 1 evidence and screenshots.

**Outside the repository:** scratch copies for the mutation check live in the session scratchpad only.
