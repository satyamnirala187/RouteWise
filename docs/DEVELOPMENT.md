# Local development (Phase 1)

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
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/alembic upgrade head

# 3. Users. No public sign-up: create accounts locally. The password is typed at a hidden prompt
#    (or piped on stdin), never passed as an argument, never committed.
.venv/bin/python -m routewise_api.cli create-user --username admin1 --role admin
.venv/bin/python -m routewise_api.cli create-user --username rider1 --role rider --name "Rider One" --vehicle scooter
#    later: set-password --username rider1 | deactivate --username rider1   (both end existing sessions)

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

Open http://localhost:5173 and sign in. Admins land on **Orders** (and **Import**); riders land on **My deliveries**.

**Production-style single origin (local check only, not a deployment):** `cd apps/web && npm run build`, then run the API alone. It serves `apps/web/dist` at http://127.0.0.1:8000. In production, set `ROUTEWISE_ENV=production`; the app then refuses to start without Secure cookies and uses the `__Host-` cookie prefix.

## Tests

```bash
cd services/api && .venv/bin/python -m pytest -q             # API: real PostgreSQL (routewise_test), migrations, mocked network
cd apps/web && npm run typecheck && npx vitest run            # frontend type checks + unit tests
scripts/e2e.sh                                                # Playwright, desktop + mobile, isolated routewise_e2e DB, screenshots
cd spikes/routing && .venv/bin/python -m pytest -q            # Phase 0 routing regression
python3 services/api/tools/mutation_check.py <copy of services/api> services/api/.venv/bin/python   # optional
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
