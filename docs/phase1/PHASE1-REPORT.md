# Phase 1 report — foundation, secure sign-in and Excel import

> **Accepted by the owner on 13 October 2026 for local development** at `fcac55e` ([owner acceptance record](OWNER-ACCEPTANCE-2026-10-13.md)). The acceptance covers local development only; real phones, Safari/Firefox, live short links, accessibility, CI, production HTTPS, backups, load testing and retention cleanup remain unperformed. The text below is the historical record as written before acceptance. Its "awaiting owner review", "uncommitted" and "pending sign-off" statements describe that time and are kept unchanged. Phase 2 work is tracked in [../phase2/](../phase2/IMPLEMENTATION-PLAN.md).

**Date:** 13 October 2026 · **Prepared by:** Claude Code · **Status: implemented locally; awaiting owner review.** Phase 2 has not started. Nothing is deployed and nothing was spent (₹0).

**Revision:** base commit `2a34226` (the accepted Phase 0 baseline). **All Phase 1 changes, including the correction pass, are uncommitted** in the working tree; no commit has been made for Phase 1 yet. No remote exists, and nothing was pushed.

**Baseline recorded:** the owner's Phase 0 acceptance is copied byte-for-byte to [`docs/phase0/OWNER-ACCEPTANCE-2026-10-13.md`](../phase0/OWNER-ACCEPTANCE-2026-10-13.md) (SHA-256 `32f4b4bf…e51a`, identical to the source). The Phase 0 report, acceptance results, Valhalla evaluation and Notion proposal each received a dated "accepted baseline" banner; their historical text and results are unchanged. The original documentation package was not modified.

## 0. Correction pass — 13 October 2026 (independent review)

An independent review found three issues. All are fixed, with regression tests, and the full verification below was re-run afterwards.

| Finding | Fix | Proof (real PostgreSQL; network mocked) |
|---|---|---|
| **Concurrent import saves.** Two commits (or a commit and a discard) could both read `state="preview"` and create duplicate rounds and orders | Commit, discard, view and expiry read the batch with `SELECT … FOR UPDATE`, so transitions take turns on the row and the loser sees the committed state. **Also found:** FastAPI's default dependency scope ran our DB commit *after* the response was sent, so a failed commit could still have been reported as success. Every `get_db` is now `scope="function"`, so the commit completes before the response | `tests/test_concurrency.py`: an outside connection holds the row lock until PostgreSQL shows both requests waiting, then releases it. Two commits → exactly **one round and one set of 5 orders**, the loser gets **409 "This import was already saved or discarded"**. Commit vs discard (3 rounds, either may win) → never both succeed, and state matches. A racing commit of an expired preview → 409/410 and nothing saved. A simulated commit failure → **500, nothing saved** |
| **Malformed links crashed.** `https://[broken/maps` raised `ValueError`; `https://maps.app.goo.gl/हिन्दी` raised `UnicodeEncodeError` | Narrow `ValueError` handling at URL split, port access and redirect join, turning a bad link into a needs-pin note. Non-ASCII path and query are UTF-8 percent-encoded; control characters and whitespace in the raw URL are rejected (`urlsplit` would otherwise silently strip tab, CR and LF). The status line accepts **ASCII digits only** (`"²".isdigit()` is True in Python, so `int()` could crash). No catch-all was added | `tests/test_link_robustness.py`: reviewer cases and variants in an Excel import (201, the bad rows need a pin, the good row resolves, commit succeeds) and in the location-edit endpoint (200). The Unicode short link is sent as `/%E0%A4%B9…` to the **validated IP**. Malformed redirect locations and odd status lines fall back to a manual pin |
| **Network bounds and the event loop.** The hop deadline started after DNS; `upload_import` was `async` but did blocking work | DNS runs on a 4-thread pool with a 3 s timeout, inside the deadline. One **total budget** covers DNS, connects, reads and redirects: **10 s per location edit, 30 s per import**. `upload_import` is a sync endpoint, so FastAPI runs it on a worker thread. **≤ 2 concurrent imports** (a third gets 429). Manual-pin fallback is kept | Slow DNS is cut off by the deadline (< 1 s) and by its own timeout. Redirect chains share one deadline. An import with 6 slow (1.5 s) lookups returns in **< 2.5 s** with every link needing a pin (it would take 9 s otherwise). **`/api/health` answers in < 0.5 s on the same event loop during a slow import.** A third concurrent import gets 429 |

The defect-injection check now covers these fixes too: undoing each one (row lock, commit scope, async import, DNS timeout, raw-URL check, malformed URL and redirect handling) makes the suite fail. Result: **25/25 caught**.

## 1. What was implemented

**Foundation**
- **Backend:** FastAPI 0.143 on Python 3.14.3 (`services/api`), with SQLAlchemy 2.1, Alembic 1.20 and psycopg 3.3.
- **Database:** local PostgreSQL 18.6 from EDB's official macOS binaries zip, with the checksum and Apple Developer ID signature (EnterpriseDB Corporation) verified. Run as your user on `127.0.0.1:54329` with SCRAM auth via `scripts/dev-db.sh`. No admin rights, Docker or Homebrew needed.
- **Frontend:** React 19.3 + TypeScript 7.0 + Tailwind 4.3 + Vite 8.3 (`apps/web`), with exact pinned versions at least two weeks old. In development Vite proxies `/api`, so the browser sees a single origin; the built app can also be served by the API.
- **Configuration:** `.env.example` holds placeholders only. Real secrets are generated into the git-ignored, `chmod 600` `.env`.

**Secure authentication** (Admin and Rider roles; no public sign-up)
- **Passwords:** Argon2id with a 12-character minimum. Unknown usernames are verified against a dummy hash, so timing doesn't reveal which accounts exist. Throttling: 5 failures per username or 20 per IP within 15 minutes gives HTTP 429.
- **Sessions:** server-side. The 256-bit token cookie is HttpOnly, SameSite=Lax and Path=/. In production it is also Secure, uses the `__Host-` prefix and sends HSTS. Only an HMAC of the token is stored. Expiry is **12 h idle and 7 days absolute**, revoked on the server. Logout revokes the session. Deactivating a user or changing their password ends all their sessions.
- **CSRF:** a per-session token, required in `X-CSRF-Token` on every POST/PUT/PATCH/DELETE and compared in constant time. The `Origin`/`Referer` must be an allowed origin. Login requires JSON from an allowed origin.
- **Authorization:** checked on the server for **every** protected endpoint (`require_admin` / `require_rider`). Rider queries filter by assignment ownership in SQL; another rider's order returns the same 404 as a missing one.
- **Landing screens:** Admin → Orders and Import; Rider → My deliveries.
- **Local user management:** `python -m routewise_api.cli create-user | set-password | deactivate`. Passwords are read from a hidden prompt or stdin, never from arguments.

**Excel import and order management**
- `.xlsx` only, with documented bounds: 2 MB file, 3 MB request body (rejected while streaming), 1,000 orders, 30 columns, zip-bomb and macro rejection, XML through `defusedxml`, per-field length caps.
- **Columns:** Name, Product, Contact and Location are required; Delivery Instructions is optional. Known heading aliases are mapped and shown. A title row above the header is skipped. Duplicate headers and missing required columns are file errors.
- **Row errors** carry Excel row numbers: missing fields, formulas (never evaluated), invalid contacts, scientific-notation contacts, over-long fields.
- **Contacts are kept as text,** including leading zeros and `+`. When Excel stored a contact as a number, a warning says the leading 0 or `+` is already lost. If the cell's zero-padded display format shows the original, the zeros are restored with a "please verify" warning.
- **Preview before save:** nothing is written until the admin confirms. Previews expire after 1 hour. Commit and discard drop the preview copy of the customer data. Duplicate-looking rows are flagged, not dropped.
- **Order IDs:** unique `RW-001001…` codes from a database sequence. Statuses are **exactly Pending / Postponed / Completed**, enforced by the API and by a database CHECK constraint.
- **Editable orders:** phone cards and a desktop table, inline editing with version checks (a stale edit gets 409), status selection, and clearing instructions.
- **Manual pin fallback** (coordinates) and **link replacement** with re-resolution, a "Check this pin in Google Maps" link, and an outside-service-area warning.

**Safe location resolution**
- **Full Google Maps links are parsed offline and never fetched.** A destination needs an explicit pin (`!3d…!4d…`, `q=` / `query=` / `destination=` coordinates, or `geo:`). A map camera centre or address text means *needs a pin*.
- **Short links** (`maps.app.goo.gl`, `goo.gl`) go only through `netsafe.head_redirect`:
  - https only, port 443, no userinfo, no IP-literal hosts, allowlisted hosts only;
  - DNS is resolved once and **every** answer must be a public address (private, loopback, link-local, CGNAT, multicast, reserved, unspecified and IPv4-mapped forms are all rejected);
  - **the socket connects to that validated IP itself**, and TLS uses SNI plus certificate and hostname verification for the original hostname, so DNS rebinding can't swap the target;
  - only the status line and headers are read (16 KB cap, never the body). DNS ≤ 3 s on a bounded 4-thread pool, connect + TLS ≤ 5 s, read ≤ 5 s, ≤ 8 s per hop, all inside one total budget: **10 s per location edit, 30 s per import** (DNS and redirects included);
  - malformed URLs fall back to a manual pin; non-ASCII targets are UTF-8 percent-encoded; control characters are rejected;
  - at most 4 redirects, each revalidated; the final Google Maps URL is parsed, not fetched;
  - any failure becomes "needs a pin".
- **Unresolved and invalid locations** are clearly badged.
- **Optimization validity gate:** `orders.planning_input()` is the only path to a future optimizer. It raises `NotReadyForPlanning` unless every pin is resolved and inside the DU North Campus service area (the Phase 0 routing graph box). `GET /api/admin/rounds/{id}/readiness` shows the blockers. There is no optimizer UI.

**Data needed later, without later-phase behaviour:** `riders` (with vehicle scooter/bike), `delivery_rounds`, `assignments` (one owner per order), and `orders.building_id` and `orders.version`. Assignment, routing, calling/navigation, rerouting, grouping and offline features were **not** built.

**Privacy:**
- No SQL echo; PostgreSQL `log_statement = none`.
- Validation errors never echo submitted values.
- API responses are `Cache-Control: no-store`, with a strict CSP and anti-framing headers.
- Logs carry no customer fields (tested).
- All fixtures and screenshots use synthetic data.

## 2. Database migration

`services/api/migrations/versions/0001_initial_schema.py`: autogenerated, then reviewed and edited by hand. It creates `users`, `riders`, `sessions`, `login_failures`, `import_batches`, `delivery_rounds`, `orders`, `assignments`, their check constraints (roles, three statuses, a resolved location must have coordinates, coordinate ranges, vehicles), foreign keys and indexes, and the `order_code_seq` sequence. A test checks upgrade → downgrade → upgrade, and that the schema matches the models with no diff.

## 3. Changed files

**New:**
- **Backend:** `services/api/` — `routewise_api/{config,db,models,security,deps,netsafe,locations,importer,orders,main,cli}.py`, `routers/{auth,admin,rider}.py`, `migrations/`, `alembic.ini`, `requirements.in` / `.lock`, `pyproject.toml`, `scripts/e2e_setup.py`, `tools/mutation_check.py`, and `tests/` (9 files, including `test_concurrency.py` and `test_link_robustness.py` from the correction pass).
- **Frontend:** `apps/web/` — `src/{App,main,api,useIsWide}.ts(x)`, `src/components/{Shell,Badges,OrderEditor}.tsx`, `src/pages/{Login,Orders,Import,Rider}Page.tsx`, `src/api.test.ts`, `e2e/phase1.spec.ts`, plus the package, Vite, Vitest, Playwright and tsconfig files.
- **Scripts:** `scripts/dev-db.sh`, `scripts/e2e.sh`.
- **Docs:** `docs/DEVELOPMENT.md`, `docs/phase0/OWNER-ACCEPTANCE-2026-10-13.md`, `docs/phase1/` (this report, `evidence/`, `screenshots/`).

**Modified:** `.gitignore`, `.env.example`, `README.md`, `CLAUDE.md`, `docs/README.md`, and banner-only changes to `docs/phase0/{PHASE0-REPORT,ACCEPTANCE-RESULTS,VALHALLA-LOCAL,NOTION-UPDATE-PROPOSAL}.md`.

**Not modified:** `spikes/`, `tests/fixtures/`, Phase 0 evidence, and the original documentation package.

**Outside the repository:** Playwright's Chromium headless shell (94 MB) in `~/Library/Caches/ms-playwright`; delete that folder to remove it. Local runtime data (PostgreSQL binaries and clusters, e2e state) is in the git-ignored `.local/`.

## 4. Reproducible startup

See [`docs/DEVELOPMENT.md`](../DEVELOPMENT.md). In short:

```bash
scripts/dev-db.sh install && scripts/dev-db.sh init
cd services/api && python3.14 -m venv .venv && .venv/bin/python -m pip install -r requirements.lock && .venv/bin/alembic upgrade head
.venv/bin/python -m routewise_api.cli create-user --username admin1 --role admin      # password at a hidden prompt
.venv/bin/uvicorn --factory routewise_api.main:get_app --host 127.0.0.1 --port 8000 --reload
cd apps/web && npm ci && npx vite                                                      # http://localhost:5173
```

## 5. Test results (run 13 Oct 2026 on this Mac)

### Automated (all actually run; outputs in `docs/phase1/evidence/`)

| Suite | Command | Result |
|---|---|---|
| API (real PostgreSQL, migrations, mocked network) | `cd services/api && .venv/bin/python -m pytest -q` | **150 passed** (111 before the correction pass, plus 39 new) |
| — concurrency: commit/commit, commit/discard, expiry races; failed commit never reported as success | `tests/test_concurrency.py` | included above |
| — malformed/Unicode links in import and location edit; time budgets; event-loop responsiveness; import concurrency cap | `tests/test_link_robustness.py` | included above |
| — auth, expiry, logout, throttling, cookies, hashing, CLI | `tests/test_auth.py` | included above |
| — every endpoint: anonymous 401, rider→admin 403, admin→rider 403, CSRF (missing, wrong, other session's token, cross-origin) on every mutation, cross-rider isolation | `tests/test_permissions.py` | included above |
| — import validity, limits, contacts, preview/commit/discard/expiry | `tests/test_import.py` | included above |
| — editing, statuses (API + DB constraint), manual pin, link correction, readiness gate | `tests/test_orders.py` | included above |
| — link parsing, private-IP rejection, validated-IP connect, TLS hostname, rebinding, redirects, header and time bounds | `tests/test_locations.py` | included above |
| — migrations round-trip and match the models; no customer data in logs or error echoes; SPA path traversal | `tests/test_migrations_privacy.py` | included above |
| Frontend type checks | `npm run typecheck` | **OK** (app + node configs) |
| Frontend unit tests (API client: CSRF only on mutations, same-origin, no browser storage) | `npx vitest run` | **5 passed** |
| Frontend production build | `npm run build` | **OK** |
| Browser end-to-end (Chromium; desktop 1280×800 and mobile 390×844 with touch) | `scripts/e2e.sh` | **8 passed** (4 scenarios × 2 viewports) |
| Phase 0 routing regression (unchanged) | `cd spikes/routing && .venv/bin/python -m pytest -q` | **264 passed, 5 skipped** (same as the accepted baseline; `evidence/phase0_regression.txt`) |
| Local Valhalla live checks | `ROUTEWISE_LIVE_TESTS=1 … -m live tests/test_valhalla_du.py` | **2 passed** |
| Defect-injection check (25 injected security/correctness bugs, 7 of them from the correction pass) | `tools/mutation_check.py` on a scratch copy | **25 / 25 caught** |

### Checks I made by hand

- **Screenshots, mobile (390 px) and desktop (1280 px):** sign-in error, import preview, orders blocked, order edited, rider list. Each was opened and inspected. This found and fixed two real problems:
  1. Both layouts were rendered at once, duplicating editors.
  2. Import names showed UTC time.
- **Developer startup on the dev database:** CLI-created users, API on :8000 and Vite on :5173. The proxied sign-in returned the admin session and CSRF token. A cross-site sign-in got 403. The API served the built app with a JSON 404 for unknown API paths, and path-traversal probes towards `.env` returned no repository files.

### Not performed

- Real phones (iOS Safari, Android Chrome), other browsers (Safari, Firefox), and tablet widths. Mobile was emulated in Chromium only.
- **A live short-link resolution against `maps.app.goo.gl`.** Network security was tested only with mocked DNS, sockets and TLS, as required.
- A screen-reader or accessibility audit beyond labelled controls and 44 px touch targets; human usability testing.
- HTTPS deployment, production configuration, backups, CI (no remote or CI service exists), and load or performance testing.

## 6. Screenshots (synthetic data)

| | Mobile (390 px) | Desktop (1280 px) |
|---|---|---|
| Sign-in error | [mobile-01](screenshots/mobile-01-login-error.png) | [desktop-01](screenshots/desktop-01-login-error.png) |
| Import preview (title row skipped, numeric-contact and needs-pin warnings) | [mobile-02](screenshots/mobile-02-import-preview.png) | [desktop-02](screenshots/desktop-02-import-preview.png) |
| Orders: planning blocked by one missing pin | [mobile-03](screenshots/mobile-03-orders-blocked.png) | [desktop-03](screenshots/desktop-03-orders-blocked.png) |
| Order edited: manual pin and status | [mobile-04](screenshots/mobile-04-order-edited.png) | [desktop-04](screenshots/desktop-04-order-edited.png) |
| Rider sees only own deliveries | [mobile-05](screenshots/mobile-05-rider-list.png) | [desktop-05](screenshots/desktop-05-rider-list.png) |

## 7. Failures, limitations and open points

**No failures remain in the final runs (re-run after the correction pass).** These were found and fixed along the way:
- *Correction pass:* unlocked import transitions, a commit that ran after the response, crashes on malformed or Unicode links, Unicode digits in the status line, silently stripped control characters, a DNS lookup with no deadline, and import work on the event loop (details in section 0).
- A title row was treated as the header.
- Two layouts were rendered at once.
- Import names used UTC.
- The PostgreSQL signer check misfired under `pipefail`.
- A `test` key sat in the Vite config.
- A body-read test had the wrong premise.

**Limitations:**
1. **There is no assignment UI yet (Phase 2),** so riders see an empty list in normal use. Isolation is proven with seeded assignments.
2. **Retention (D10, 30 days) is not implemented.** Expired import previews are cleared only when accessed, and expired sessions only when reused; there is no background sweeper yet. Both belong with the retention/purge work.
3. **Manual pins are typed coordinates;** there is no map picker, because a tile provider decision is pending.
4. **The short-link client connects to the first validated address only,** with no IPv4/IPv6 fallback. That's deliberate for simplicity, but it may fail where IPv6 is unreachable; the fallback is a manual pin.
5. **Login throttling keys on the direct client IP.** Behind a reverse proxy, forwarded-header handling must be configured at deployment.
6. **The CSP allows inline styles** (`'unsafe-inline'` for styles only).
7. **Only the first worksheet is imported. Legacy `.xls` and CSV are rejected** (a decision was required, and none was made).
8. **Correction-pass notes:**
   - A system DNS lookup that hangs can't be interrupted. It finishes on its own thread, but there are at most 4 such threads; requests past the deadline get "could not be checked".
   - The import concurrency cap is per API process. Several processes in a deployment would each allow 2.
   - In a scratch copy without a built frontend, the SPA traversal test skips (it passes in the real tree).
9. **Tooling notes:**
   - Starlette warns that `TestClient` with `httpx` is deprecated.
   - npm left `fsevents`' install script unapproved; it's optional and prebuilt.
   - TypeScript 7.0 is new.
   - PostgreSQL comes from EDB's zip build: a local development choice, not a hosting decision.

## 8. Phase 1 acceptance checklist

| Gate item (roadmap and kickoff) | Result |
|---|---|
| Owner approval recorded; historical evidence kept separate | ✅ Copied record, plus banners only |
| React/TS/Tailwind + FastAPI + PostgreSQL with versioned migrations | ✅ Migration 0001 round-trip test |
| Startup instructions; `.env.example` placeholders only | ✅ `docs/DEVELOPMENT.md`; scan found no secrets |
| Argon2id hashing, server sessions, server authorization on every endpoint | ✅ Route-inventory tests |
| CSRF on every mutation; dev and production cookie settings | ✅ |
| 12 h idle / 7 day absolute expiry, logout, role landing screens | ✅ API + e2e |
| No public sign-up; documented local user creation without committed passwords | ✅ CLI |
| A rider cannot access another rider's data (server-side) | ✅ API + browser |
| A valid fixture imports correctly; malformed data gets useful row errors | ✅ |
| Bounded file/row/parse resources, documented | ✅ |
| Contacts and leading zeros preserved; warning when Excel lost them | ✅ |
| Unique order IDs, preview before save, persisted in PostgreSQL | ✅ |
| Editable, mobile-friendly orders; three statuses only | ✅ API, DB and UI |
| Manual pin fallback; unresolved pins shown clearly; invalid pins block planning | ✅ |
| SSRF / rebinding-safe short links with validated-IP connect and HTTPS identity | ✅ mocked network |
| Import commit/discard/expiry are concurrency-safe; the commit finishes before the response | ✅ real PostgreSQL race tests |
| Malformed or Unicode links can't crash an import or a location edit | ✅ regression tests |
| Total link-check budget includes DNS and redirects; the event loop is never blocked; imports are bounded | ✅ timing tests |
| Customer data out of logs, fixtures and unauthorized responses | ✅ tested |
| Phase 0 regression intact | ✅ 264 passed / 5 skipped |
| No Phase 2+ features | ✅ none built |
| Secrets stay server-side; basic checks pass | ✅ locally; ⚠️ **no CI** (no remote) |
| Real-device and live short-link checks | ⏳ Not performed |
| Owner sign-off | ⏳ Pending |

## 9. Proposed Notion updates (NOT applied; for owner review)

| Record | Proposed change |
|---|---|
| Phase P0 | → **Done**, approval 13 Oct 2026, revision `2a34226`, evidence `docs/phase0/OWNER-ACCEPTANCE-2026-10-13.md` (if not already recorded) |
| Phase P1 | Not started → **In review**; start 13 Oct 2026; QA evidence `docs/phase1/PHASE1-REPORT.md`; Commit: *(blank until committed)* |
| P1-01 Scaffold frontend, backend, database | → **In review** (pinned versions, migration 0001) |
| P1-02 Secure sessions and roles | → **In review** (Argon2id, server sessions, CSRF, 12 h/7 d, route-inventory tests) |
| P1-03 Excel validation and extraction | → **In review** (bounded import, row errors, contact preservation) |
| P1-04 Resolver and editable order review | → **In review** (pinned-IP short-link client, manual pins, readiness gate) |
| P1-05 Foundation QA and gate | → **In review**. Note: no CI or real-device checks yet |
| A07 Required Excel fields | Not run → **Passed** (`test_import.py`) |
| A08 Optional instructions and contact strings | Not run → **Passed** |
| A09 Ambiguous map link and manual correction | Not run → **Passed** |
| A10 Resolver security | Not run → **Passed (mocked network)**; live short link not run |
| A11 Role and ownership isolation | Not run → **Passed** (API + browser) |
| Decisions (new, proposed) | Local PostgreSQL from EDB binaries for development; session/CSRF design as implemented; `.xlsx` only (no `.xls`/CSV); manual pins by coordinates until a map tile provider is chosen |
| Home callout | "Phase 0 accepted 13 Oct (local). Phase 1 implemented locally and in review; nothing deployed; ₹0." |
