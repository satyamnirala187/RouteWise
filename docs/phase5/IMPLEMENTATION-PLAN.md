# Phase 5 implementation plan: offline PWA, privacy cleanup, deployment preparation and pilot

**Status: PROPOSAL for owner review. Nothing in this plan is implemented, authorized or approved as a step.** No application code, schema, dependency or deployment changed in preparing it. The owner asked for planning only; step 5A starts only when the owner asks for it.

| | |
|---|---|
| Date | 28 October 2026 |
| Prepared by | Claude Code |
| Baseline | `main` at `4609df5` (PR #10 merged). Phase 4 accepted for local development on 28 Oct 2026 ([record](../phase4/OWNER-ACCEPTANCE-2026-10-28.md)); Phases 0 to 3 accepted earlier. Migration head is `0006` |
| Approval | None yet for any Phase 5 step |

**Constraints that apply to every step:**
- ₹0 budget. Existing local Valhalla only (`spikes/valhalla/data/valhalla_tiles`). No paid service. Public deployment is **not** established.
- Order statuses stay exactly Pending / Postponed / Completed. No new status, no fuel analytics, no postponed dashboard, no compulsory confirmation.
- No device GPS tracking and no stored device-position history (one-shot position for a reroute only, as in 4D). Rerouting needs connectivity (R22).
- `docs/source/` is verbatim and is not edited. Historical evidence (`docs/phase*/evidence`, screenshots) is not rewritten. Notion is updated by a human.
- Customer fields never reach logs, analytics, crash reports, QA evidence or Git. The repository is public, so this plan names no real address, host account or credential.
- Only the owner runs `phone_db.py upgrade` or `phone_setup.py`; `routewise_phone` is not touched by any step unless the owner says so.

**How to read it.** *Approved* means the owner approved it (or it is a confirmed requirement). *Proposed* means this plan suggests it and the owner has not decided. Proposals are never presented as approvals.

## 1. What is already approved (and where)

| Item | Source |
|---|---|
| R21 save own rider list offline, queue status changes, synchronize on reconnect; R22 reoptimization needs connectivity; R24 privacy safeguards; R16 three statuses; D11 reroutes preserve other riders' packages | [Product](../source/notion/RouteWise/01-Product.md) |
| Own-rider snapshot expires **18 hours** after the last successful sync | D09, [Phase 0 acceptance](../phase0/OWNER-ACCEPTANCE-2026-10-13.md) |
| Sessions: **12-hour idle** and **7-day absolute** limits. After expiry, queued operations stay on the device but are not sent until the rider signs in again | D09 |
| Offline status operations: unique operation ID, authorization, version check, **idempotent replay** (a duplicate returns the original acknowledgement) | D09, [Privacy](../source/notion/RouteWise/07-Privacy.md) |
| A stale write **never** undoes a Completed order | D09 |
| Logout with unsynced operations **warns before deleting** them | D09 |
| Customer-detail retention **30 days**, then purge or anonymize. Public hosting deferred to deployment planning, "not asserted free or ready" | D10 |
| Own-rider storage defaults: own orders, own stop coordinates, own endpoint; never other riders' data, admin views or the full import; partition by account; service worker caches the app shell only | [OFFLINE-PRIVACY.md](../phase0/OFFLINE-PRIVACY.md) as approved defaults at Phase 0 acceptance |
| Phase 5 gate: airplane-mode, reopen and reconnect tests without lost or duplicate accepted updates; no offline reoptimization claim; security regressions pass; pilot has real observations; deployment and restore/rollback evidence; owner sign-off | [Roadmap](../source/notion/RouteWise/04-Roadmap.md) |
| Cases A22 to A28 and tasks P5-01 to P5-04 | [Acceptance-Cases.csv](../source/notion/RouteWise/Acceptance-Cases.csv), [Tasks.csv](../source/notion/RouteWise/Tasks.csv) |
| Pilot measures, stop conditions and "release needs human approval, deployment evidence, backups and rollback readiness" | [Pilot](../source/notion/RouteWise/10-Pilot.md) |

D09 and D10 are still marked *Pending* in the verbatim Notion export (`docs/source/` is not edited). The Phase 0 acceptance record is what approved their values.

**Still pending from earlier phases (not decided here):** Q4-6 (real-phone secure-context route), the provisional 4B/4C defaults, Phase 2 proposals Q1 to Q8, and the unidentified, unreproduced backend failure at the 4D checkpoint. Q1 ("all orders Pending" replanning restriction) is not built.

## 2. What the code does today (read at `4609df5`)

**Frontend** (`apps/web`: React 19, react-router 8, Vite 8, Tailwind 4):
- There is **no service worker, no manifest, no `public/` folder, and nothing stored in the browser**. `api.ts` says so, and `expectNoBrowserStorage` asserts zero `localStorage`, `sessionStorage` and IndexedDB entries at 16 call sites in the Playwright specs (phase 2 to 4). Phase 5 deliberately changes that rule for riders only.
- The build output is `dist/index.html` plus one hashed JS file and one hashed CSS file. Small shell.
- `App.tsx` treats **any** `loadSession()` failure, including a network failure, as "not signed in" and redirects to `/login`. So even with a cached shell, an offline start would land on the login screen. This is the second half of the "dinosaur" problem (§3.2).
- `RiderPage.tsx` shows a status change only after the server confirms it. A network failure shows "may or may not have reached the server, retry". `RerouteSection` already disables recalculation offline: "nothing is queued". Both stay true for rerouting.
- `useOnline` reads `navigator.onLine`, which can say "online" without a working connection.

**Backend** (`services/api`: FastAPI, SQLAlchemy, Alembic, PostgreSQL):
- Sessions already have `session_idle = 12 h` and `session_absolute = 7 d` (`config.py`, `deps.session_expired`); the cookie is `HttpOnly`, `SameSite=Lax`, `__Host-` prefixed when Secure. Offline time counts as idle, because only a server request updates `last_seen_at`.
- 401 bodies are plain strings ("Not signed in", "Session expired; sign in again", "Account disabled"). `/api/auth/session` returns username, role, rider name and the CSRF token, but **no user id**.
- Status API: `POST /api/rider/orders/{id}/status` with `status` and `expected_version`. Ownership is checked first (another rider's order is a 404). It locks the order row then the round. A request for the status the order already has returns `changed: false`. A version mismatch is 409 `order_changed`; a reassigned order is 409 `order_reassigned`; a transition outside Pending→Completed / Pending→Postponed / Postponed→Pending is 422, so **a rider can never reopen Completed**. The response carries the refreshed delivery view.
- Gap for Phase 5: there is no operation ID or ledger. A repeat of the same status is harmless, but the server cannot tell "my earlier request" from "someone else already did this", so a lost response after an admin edit gives an ambiguous answer.
- The delivery view holds customer name, product, contact, instructions, the order pin, status and `version`, plus a `reroute` block that names the last completed stop's customer. It does not contain the rider's Home or Custom coordinates.
- Non-API responses carry no `Cache-Control`; `/api/*` carries `no-store`. The CSP is `default-src 'self'` with no `worker-src`, so a same-origin worker is allowed by fallback. The SPA route serves any existing file in `dist` as-is and `index.html` for everything else that is not `/api/`.
- Retention is not implemented ([SECURITY-REVIEW](../SECURITY-REVIEW.md): "No retention purge (D10)"). Expired import previews and sessions are cleaned only when touched. There are no backups, no HTTPS and no deployment. CI runs Web, API, Routing and CodeQL; the Playwright suites run locally only (`scripts/e2e.sh`).
- Customer data lives in `orders` (name, product, contact, instructions, link, pin, `building_id`), in `import_batches.rows` until commit or discard, and as Home/Custom coordinates in `rider_endpoints`. Plans, revisions and runs hold order ids, sequence and totals, no customer fields and no coordinates.

**Observed on a phone (owner-reported, Phase 4):** refreshing the page while offline showed Chrome's offline ("dinosaur") page. Rerouting was correctly disabled and recovered after reconnecting ([results](../phase4/PHONE-TEST-RESULTS.md) row 5).

## 3. Core design (all proposed unless §1 says otherwise)

### 3.1 Three stores, never mixed

| Store | Holds | Never holds | Lifetime |
|---|---|---|---|
| **App shell** (Cache Storage, `rw-shell-<build>`) | `index.html`, hashed JS/CSS, manifest, icons | Any API response, any user data | Replaced on each build |
| **Rider snapshot** (IndexedDB, one database per user id) | The signed-in rider's own rounds as delivery views (orders, customer fields, pins, statuses, versions, plan summary), `generated_at` from the server clock, `received_at` from the device | Other riders' data, admin data, the full import, Home/Custom coordinates, the reroute block, passwords, session cookies, CSRF tokens | 18 h after the last successful sync, then deleted |
| **Outbox** (same per-user database) | Queued operations: operation id, order id, order code, from/to status, versions, device time, state | Customer name, contact, address, instructions, coordinates | Until acknowledged or explicitly discarded |

- A small registry database holds only "last signed-in user id and username" and the pending-logout marker. No customer data.
- `localStorage` and `sessionStorage` stay unused. The `expectNoBrowserStorage` helper changes in 5A: those two stay empty everywhere, and IndexedDB must hold only the signed-in rider's partition (nothing at all for an admin, nothing after logout).
- **Tightening of the approved defaults (proposed):** OFFLINE-PRIVACY lists "own endpoint (Home/Custom)" as storable. Since rerouting needs connectivity and the delivery view never shows those coordinates, the device does not store them. The owner can override.
- A new server endpoint `GET /api/rider/snapshot` (rider only) is the single contract for what leaves the server for offline use: it omits the `reroute` block, stamps `generated_at` and `expires_at` from the **server** clock, and covers every round the rider has a Pending or Postponed order in (newest 3), read in one consistent transaction. A field-allowlist test guards it. Reusing the live endpoints and stripping on the client was rejected: minimization belongs on the server.

### 3.2 App shell, service worker and the "dinosaur" cases

**Secure context.** Service workers register only on HTTPS or `http://localhost`. The Wi-Fi address of `scripts/phone-server.sh` (plain HTTP) can never run the offline shell; that is a browser rule, not a defect. Device checks use `localhost` over USB (`adb reverse`, the owner's Q4-6 route) until HTTPS exists. **Airplane mode does not cut an `adb reverse` tunnel**, so a phone "offline" test must stop the server or unplug USB after the page has loaded.

**Worker behaviour (proposed):**
- Registered only when `isSecureContext` and in production builds. The Vite dev server is unaffected.
- Install: precache exactly the build's shell files (list generated from the build output, never hand-maintained), fetched with `cache: "reload"`.
- Fetch: a navigation to a non-`/api/` path gets the cached `index.html` (the same fallback the SPA route gives online); a request for a precached file gets its cached copy; **everything else, and every `/api/` request, is not intercepted at all**. No runtime caching, no fallback pages for the API.
- Activate: delete every `rw-shell-*` cache except the current one.
- Served by the API with `Cache-Control: no-cache` for `/sw.js`, `/index.html` and the manifest, and `public, max-age=31536000, immutable` for `/assets/*`; `/sw.js` served as JavaScript at the root so its scope is `/`. `/api/*` keeps `no-store`.
- No new dependency: a small build plugin emits `sw.js` and the manifest data; the routing rules live in a plain module that vitest can test.

**Updates and invalidation (proposed).** A new build changes `sw.js` bytes (build id plus file hashes), so the browser installs it beside the old one. It does **not** take over automatically: the app shows "Update available" and the new worker activates on the next launch or when the rider taps it, never in the middle of a sync. The IndexedDB schema is versioned; a migration may never drop the outbox. The API stays compatible with the previous app build for one release (the status endpoint accepts a request without an operation id). Kill switch: a build whose `sw.js` unregisters itself and clears `rw-shell-*`; 5C rehearses it.

**Each dinosaur case:**

| Case | Today | After 5A |
|---|---|---|
| D1. Refresh the page while offline (observed) | Chrome's offline page | Cached shell loads, then the rider snapshot |
| D2. Cold start offline from a tab or home-screen icon | Offline page | Same, if the worker was installed on an earlier online visit |
| D3. First ever visit while offline | Offline page | **Cannot work.** Documented; a "Ready for offline" indicator shows only when the worker is active, the precache is complete and a snapshot exists |
| D4. Plain-HTTP Wi-Fi address | Offline page | Unchanged; no secure context, no worker |
| D5. Browser cleared the site data, or evicted storage | Offline page | Offline page. Residual risk (§6). `navigator.storage.persist()` is requested to lower it |
| D6. "Online" but unreachable (captive portal, weak signal) | Spinner, then error | Shell is served from cache at once; API calls time out after a bounded wait (bounded, e.g. 10 s) and count as offline |
| D7. Deep link or `?round=` URL offline | Offline page | Shell, then the same route logic |
| D8. Admin pages offline | Offline page | Shell loads and says admin needs a connection. No admin data is ever cached or stored |

**Bootstrap fix.** `loadSession` must tell a definite server answer from no answer. A definite 401 means "sign in". A network error or timeout means "offline": if a registry entry exists, the user is a rider and an unexpired snapshot exists, the app opens in offline mode. It never fakes a session; offline mode has no CSRF token and sends nothing. **There is no offline login**: with no partition, an offline start shows "Connect to sign in".

### 3.3 Identity, expiry, revocation and account switching

- Add the opaque `user_id` to `/api/auth/session` (the user's own id) so partitions are keyed by id, not by a reusable username.
- Add a machine-readable `code` to the three 401 bodies (`not_signed_in`, `session_expired`, `account_disabled`); the client must not match message text. Existing tests that assert the strings are updated.
- **Only a definite server 401 locks the snapshot; a network failure never does.** Online with `session_expired`: the login screen shows, the snapshot stays on the device but hidden until the same user signs in. Online with `account_disabled`: the snapshot is deleted at once and the outbox is kept but never sent (the rider is told to contact their admin, §3.5).
- Snapshot expiry runs on the device clock: `now - received_at > 18 h` deletes the snapshot at the next app open or timer tick. A device clock moved backwards (below a stored high-water mark) counts as expired. This is a heuristic and not a security boundary against someone who controls the device; the protections are the device lock, the 18-hour limit and logout/switch deletion. The worst case for a disabled rider whose phone never reconnects is 18 hours after the last sync.
- **Reauthentication before sync.** The sync runner sends nothing without a live session. On 401 it stops in an `auth_required` state, keeps every operation, and the app asks for sign-in. After sign-in the returned `user_id` must equal the partition owner, otherwise it is an account switch.
- **Logout** (5B, once an outbox exists): if unsynced operations exist, a dialog offers *Sync now*, *Log out and delete them* (states that the changes will be lost) or *Cancel*. In 5A, with no outbox, logout deletes the snapshot. Offline logout clears local data and records a pending-logout marker; the HttpOnly cookie can only be cleared by the server, so the app sends the logout when it is next online.
- **Account switch** on a shared device: signing in as another user deletes the previous user's **snapshot** immediately (customer data gone, A26). The previous user's **outbox** holds no customer fields, so it is kept (counts and order codes only) until that user signs in or someone discards it explicitly after a warning. This reconciles "always clears the previous user's partition" with "warns before deleting unsynced operations"; it is a proposal (Q5-8).
- An admin sign-in on the device is an account switch and never creates a partition.

### 3.4 Saved server status versus queued local changes

No fourth status. A pure function `effectiveView(snapshot, outbox)` produces what the screen shows:
- `savedStatus` and `savedVersion` come only from the last server answer. `effectiveStatus` = the target of the latest unacknowledged operation, else `savedStatus`.
- The order card shows the effective status in the existing pill, plus a **separate marker**: "Waiting to sync" (queued), "Syncing" (in flight) or "Not saved, review" (rejected). When the two differ, the card also says "Saved on server: Pending".
- Sections (next stop, Postponed, Completed) follow `effectiveStatus`, so a stop completed offline advances "Next" and the quick-call target. The saved route sequence is not recomputed offline; an order returned to Pending offline appears as "not in the saved route", exactly as it does online until a reroute.
- A banner shows the count of waiting changes, last sync time, snapshot age and expiry. Nothing is ever described as saved before the server acknowledges it.

### 3.5 Operations: ordering, duplicates, lost responses, conflicts, crashes (5B)

**Client record:** `op_id` (UUID v4, created at tap), `user_id`, `round_id`, `order_id`, `order_code`, `from_status`, `to_status`, `base_version`, `client_time` (display only), a per-device sequence number, `state` (`queued`, `sending`, `done`, `rejected`), attempt count, last error code. The `op_id` is also sent on **online** taps, so online and offline use one path.

**Server (migration `0007`, table `status_operations`):** primary key (`rider_id`, `op_id`), `order_id`, `expected_version`, `to_status`, `outcome` (`applied`, `noop`, `rejected`), `result_code`, `resulting_status`, `resulting_version`, `received_at`, `client_time`. No customer fields. It is written inside the same transaction and under the same order→round locks as the status change.

| Situation | Behaviour |
|---|---|
| First sight of an operation | Existing checks, in order: ownership, version, transition. The outcome is stored with the status change (or the rejection) and returned as an acknowledgement with `resulting_version` |
| Duplicate request (retry, double tap, two tabs) | Ledger lookup under the order lock returns the stored acknowledgement with `replayed: true`. Nothing is applied twice |
| Same `op_id`, different content | 422 `op_id_reused`; the ledger entry is untouched |
| Lost **response** | Client resends the same operation, gets the stored acknowledgement |
| Lost **request** | Never reached the server; the resend is a first application |
| Several operations on one order | Sent strictly in creation order, one at a time. Operation k+1's `expected_version` is bound at send time from acknowledgement k's `resulting_version`. If k is rejected, later operations on that order are held, not rebased; other orders continue |
| Admin or another change in between | Version mismatch: 409 `order_changed` with the current status and version. Shown as "Not saved, review". The rider chooses *Discard my change* or, if the transition is still allowed from the current status, *Apply to the latest*, which creates a **new** operation. No silent rebase (Q5-3) |
| Order reassigned meanwhile | 409 `order_reassigned`; the order leaves the list at the next refresh; a "not applied" entry shows the order code only |
| Stale operation against a Completed order | Cannot succeed: the transition table has no way out of Completed and the version has moved. Tested for every status/operation pair |
| Admin reopens a Completed order, then the original completing operation is replayed | The stored acknowledgement is returned; it is **not** applied again |
| Account disabled | 401 `account_disabled`; operations kept and never sent; the rider is told to contact their admin (no admin tooling in 5B) |
| Crash or reload while `sending` | On start, `sending` becomes `queued`; replay is safe by design |
| Storage full or blocked | The tap is refused with a visible message. A tap is never accepted and then lost |
| Two tabs | One sync runner at a time (Web Locks); enqueueing is a single IndexedDB transaction |

After a drain with nothing left queued, the client refreshes the snapshot and shows server truth, naming any order the admin changed after the rider's accepted update.

**Triggers:** app open, the `online` event, the page becoming visible, after each queued tap while online, and a *Sync now* button. Background Sync is Chromium-only and is **not** relied on. Consequence, stated plainly: a change made offline is sent only when the app is next open and online. The "N changes waiting" marker is the mitigation.

**Device time** affects display order only. Server time and authorization decide the accepted state.

### 3.6 Retention, purge and backups (5C)

**Proposed meaning of the D10 rule.** Customer details are kept while a round is active and for 30 days after its last activity (latest order change, plan or admin edit); then the round is purged by anonymizing in place, which keeps counts, statuses, times and routes for pilot metrics without personal data. Hard deletion is the alternative (Q5-5). What starts the clock is a genuine question (Q5-4); a round has no closed state today.

| Data | Action at purge | Note |
|---|---|---|
| `orders` | Overwrite name, product, contact, instructions, link and location note with fixed placeholders; set pin to unresolved (the existing constraints require `needs_correction` when coordinates are empty); clear `building_id` | Status, version, timestamps and ownership stay |
| `rider_endpoints` (Home/Custom) | Delete the row | Same schedule proposed (Q5-7); also required by R24 |
| `import_batches.rows` and expired previews | Clear | Today cleared only when touched; a sweeper makes it unconditional |
| `sessions`, `login_failures` | Delete expired or revoked rows | Housekeeping; IP addresses live in `login_failures` |
| Plans, revisions, runs, `status_operations` | Kept | The Phase 4 plan says revisions hold no coordinates; run errors can name order codes and riders. 5C's scan of every text and JSON column checks all of it before anything is claimed |
| Device snapshot | Expires at 18 h on its own; deleted on logout or switch | Outbox never holds customer fields |
| Logs | No customer fields by existing tests; rotation of server logs matches the retention period | Host decision |
| **Backups** | See below | The hard part |

**Backups.** "Back up with the same retention" cannot mean a customer detail disappears everywhere on day 30: a dump taken on day 29 still holds it. The honest worst case is **30 days plus the backup retention period**. The plan proposes daily dumps kept 14 days (worst case 44 days) and asks the owner to accept that or shorten it (Q5-6). **Restoring a backup must not resurrect purged data:** the purge keeps a ledger of purged round ids (no personal data) and the restore procedure re-runs the purge before the app starts. Backup files are never placed in Git, are encrypted if they leave the host, and a restore is rehearsed on a scratch database.

**Mechanism (proposed):** a `purge` command in `routewise_api.cli` with `--dry-run` (counts only) and an injectable clock for tests; migration `0008` adds `delivery_rounds.purged_at` so the job is idempotent and visible. It is run by the host's scheduler (cron, launchd or systemd), not by an in-process thread, so a failure is visible and the single-API-process rule is untouched.

### 3.7 Verification layers

1. **Mocked network, fast** (vitest, and Playwright `route` against the Vite-served app): fetch failures, timeouts, 401 variants, 409/422 bodies, clock changes (fake timers). The storage layer is an interface with an in-memory adapter for vitest; the real IndexedDB adapter is exercised in the browser. No `fake-indexeddb` dependency is planned.
2. **Built app served by FastAPI in Chromium** (`playwright.fastapi.config.ts`, the pattern from the geolocation regression). Offline means a **real** connection refusal: the spec starts and kills its own API process, so the service worker's own requests fail too. Playwright's `setOffline` may not reach worker-initiated requests in Playwright 1.63; 5A verifies this first and records the result. Mocked-network tests never stand in for this layer.
3. **Owner phone checks** (OnePlus Nord 5, Chrome, USB/localhost; later HTTPS). Recorded as owner-reported results, kept apart from automated evidence, with no addresses, credentials or coordinates, exactly as in Phase 4.

The Playwright FastAPI suite is local-only today; 5C proposes a CI job for it (installing Chromium on a public-repo runner costs ₹0 but adds minutes).

### 3.8 Hosting facts (checked 28 Oct 2026; none was tried, no account was opened)

Hard requirements for offline: a **stable HTTPS origin** (the worker, IndexedDB and cookies are all per-origin, so a hostname that changes on restart wipes a rider's offline state), persistent PostgreSQL storage, the 51 MB Valhalla tiles, and a planner that fits in memory (the benchmark process peaked at about 1.35 GB; the API process under planning was **not** measured).

| Option | What the vendor's page says | Fit for this project |
|---|---|---|
| Owner-run machine behind a tunnel | Cloudflare Tunnel "available on all plans", outbound-only connections ([docs](https://developers.cloudflare.com/tunnel/)). That a named tunnel needs a domain on Cloudflare DNS comes from third-party posts, **not confirmed from Cloudflare's docs**; a domain is not ₹0. Quick tunnels (random address, no uptime guarantee) change hostname, so they are **unusable** for offline. Tailscale Funnel gives a stable `*.ts.net` HTTPS name with no custom domain, on ports 443/8443/10000, with non-configurable bandwidth limits ([docs](https://tailscale.com/docs/features/tailscale-funnel)); free-plan availability is from a secondary source | ₹0 and everything already runs on that machine. Cost: availability is that machine being awake and online, and Funnel puts the login page on the public internet |
| Oracle Cloud Always Free (Arm VM) | Official page: 1,500 OCPU-hours and 9,000 GB-hours a month (about 2 OCPU / 12 GB), 200 GB block storage, 10 TB outbound, home region only, "out of host capacity" errors possible; idle instances may be reclaimed if CPU, network and (Arm) memory stay under 20% over 7 days ([page](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm)). Older "4 OCPU / 24 GB" figures still circulate; the page I read says 2 / 12 | Plausible size. Risks: capacity, reclaim, and a hostname and certificate for a ₹0 VM (a domain costs money; free dynamic-DNS names and IP-address certificates were **not verified**). Whether sign-up needs a payment card was not checked |
| Google Cloud Free Tier VM | One non-preemptible `e2-micro` per month in `us-west1`, `us-central1` or `us-east1`, 30 GB disk, 1 GB a month outbound from North America; a billing account is required; limits can change on 30 days' notice ([page](https://docs.cloud.google.com/free/docs/free-cloud-features)) | Doubtful: US-only regions, a 1 GB egress allowance with no stated cap on overage, and an `e2-micro` has about 1 GB of memory against the 1.35 GB planner benchmark |
| Render free | Free services "Do not use them for production applications"; spin down after 15 minutes idle (about a minute to wake); local files lost on restart; free Postgres expires after 30 days, is 1 GB, and has no backups ([page](https://render.com/docs/free)) | **Ruled out** by the backup, restore and retention requirements alone |
| Fly.io | Third-party summaries and the discontinued-plans page report no free allowance for new organizations, only a short trial; the official pricing page was not read ([page](https://fly.io/docs/about/discontinued-plans/)) | **Ruled out** for ₹0 unless the owner finds otherwise |
| Others (Railway, Koyeb, AWS, Azure, Hetzner, serverless platforms) | Not researched | No view. Serverless platforms do not fit a long-lived FastAPI + PostgreSQL + Valhalla process |

**Unresolved and stated as such:** no ₹0 option is proven. The honest candidates for a small human-approved pilot are the owner's machine through a stable tunnel name, or an Oracle Arm VM if capacity and a hostname can be had. The decision is the owner's (Q5-1). Steps 5A to 5C do not depend on it: 5C produces a host-agnostic runbook and rehearses it locally.

## 4. Steps

Each step is committed and reviewed on its own, ends in `docs/phase5/STEP-5X-REPORT.md`, and stops for the owner. None starts without the owner asking.

### 5A: Offline app shell and expiring own-rider snapshot (read-only)

**Scope.** The app opens offline; the rider sees their own saved list; nothing can be changed offline yet.
- *Commit 1, shell only (holds no customer data, reviewable and revertible alone):* service worker + build plugin, manifest and placeholder icons, cache headers and `/sw.js` serving, update banner, the `loadSession` offline/401 split, the "Ready for offline" indicator, and the manifest link in `index.html`.
- *Commit 2, snapshot:* `GET /api/rider/snapshot`, `user_id` and 401 codes, IndexedDB store, 18-hour expiry with the clock-back heuristic, per-user partition, logout and account-switch deletion, read-only offline `DeliveryView` (actions disabled with "Changes need a connection until offline updates arrive"), staleness and expiry banner, `storage.persist()` request.

**Out of scope:** any queue or offline write; background sync; reroute changes; retention; hosting; Safari work beyond noting behaviour.

**Depends on:** Phase 4 accepted (done). No open decision blocks it; Q5-11 to Q5-13 have defaults.

**Files and schema (proposed).**
- Web: `apps/web/vite.config.ts` and a small plugin; `src/sw/` (rules module + worker template); `public/manifest.webmanifest`, `public/icons/*` (placeholders); `index.html`; `src/offline/{db,store,identity,expiry,register}.ts`; `useSnapshot.ts`; `components/OfflineBanner.tsx`; edits to `App.tsx`, `api.ts`, `pages/RiderPage.tsx`, `components/Shell.tsx`, `components/DeliveryView.tsx` (read-only mode); `e2e/phase2-helpers.ts` (`expectNoBrowserStorage`).
- API: new `routers/rider_snapshot.py` or a section of `routers/rider.py`; `routers/auth.py` (`user_id`); `deps.py` (coded 401s); `main.py` (headers for shell, worker and manifest).
- Schema: **none**. Migration head stays `0006`.
- Docs: `docs/phase5/STEP-5A-REPORT.md`; offline dev and phone-check notes in `docs/DEVELOPMENT.md`.

**Acceptance criteria.**
1. The worker installs on `http://localhost` and on no insecure origin; it is absent on the Vite dev server.
2. D1, D2, D7 and D8 above pass in Chromium against the FastAPI-served build with a **killed** server; D3 and D4 behave as documented.
3. After a normal session, Cache Storage holds only shell URLs. No `/api/` response is cached anywhere. `/api/*` still returns `no-store`.
4. The snapshot contains only the signed-in rider's own orders and none of the excluded fields; another rider's order, an admin field and Home/Custom coordinates never appear (field-allowlist test).
5. A snapshot older than 18 hours (fake clock) is deleted and never shown; a clock moved back counts as expired.
6. Logout deletes the snapshot; signing in as another user removes the first user's snapshot and customer data (A26); an admin session never creates a partition.
7. An online definite 401 locks the snapshot; a network failure does not; `account_disabled` deletes it.
8. A new build produces a new worker; the old build keeps working until the rider accepts the update; old shell caches are deleted on activation.
9. Offline recalculation stays disabled with its existing message; no write is possible offline.
10. All earlier backend, web and browser suites still pass.

**Tests.**
- API: snapshot ownership and field allowlist (planted other-rider and admin data); no customer fields in logs; header matrix for `/`, `/index.html`, `/sw.js`, manifest, `/assets/*`, deep links and `/api/*` (the `test_permissions_policy.py` pattern, including all existing security headers); `/sw.js` is JavaScript, not the SPA fallback; coded 401s; `user_id` on the session.
- Vitest: expiry boundaries and clock-back; partition isolation and deletion; bootstrap decision table (401 / network error / timeout / expired / disabled / no partition); worker routing rules (API never intercepted, shell paths only).
- Playwright (FastAPI-served, own killable server): install, offline reload, offline deep link, Cache Storage and IndexedDB inspection, account switch, logout, expiry via `page.clock`, update from build 1 to build 2 (second copy of `dist` with a different build id). Plus mocked-network checks for slow and failing API answers.
- Existing `expectNoBrowserStorage` call sites keep passing with the narrowed helper.

**Stopping point.** Read-only offline works and is reported with evidence. The owner may check on the phone (install, load once, stop the server, reopen; record as owner-reported). 5B waits for the owner.

### 5B: Queued status changes, reconnect synchronization and conflict handling

**Scope.** Offline taps become queued operations, sync on reconnect, and surface conflicts. §3.4 and §3.5 in full.

**Depends on:** 5A reviewed. Q5-3 and Q5-8 defaults accepted or changed.

**Out of scope:** offline rerouting (R22), background sync, automatic conflict resolution, admin-side tooling for conflicts, any new status.

**Files and schema (proposed).**
- Migration `0007_phase5b_status_operations` (additive, reversible): table `status_operations`. `models.py`; `tests/conftest.py` `TABLES` and `test_migrations_privacy.py` (`EXPECTED_TABLES`, head `0007`) updated.
- API: the status endpoint accepts `op_id` and returns an acknowledgement; a request without `op_id` still works for one release; a small `status_ops.py` module keeps the ledger logic out of the router.
- Web: `src/offline/{outbox,sync,effective}.ts`, `useOutbox.ts`; `RiderPage.tsx` change flow (replaces the "may or may not have reached the server" retry with the queue); `components/SyncBanner.tsx`, `ConflictList.tsx`; the logout dialog in `Shell.tsx`; `api.ts` acknowledgement types.
- Docs: `docs/phase5/STEP-5B-REPORT.md`.

**Acceptance criteria.**
1. A status change made offline is shown immediately as waiting, survives a reload and a browser restart, and reaches the server exactly once after reconnecting; repeated reconnects and duplicate sends change nothing twice (A23).
2. A lost response is repaired by replay; a crash while sending is repaired on restart; both end with exactly one applied change.
3. The ledger returns the stored acknowledgement for duplicates and 422 for a reused id with different content.
4. No stale operation changes a Completed order, for every status/operation/version combination; an admin reopening then replaying the old completing operation re-applies nothing.
5. A conflict, a reassignment and a disabled account each show a clear message, lose nothing silently, and never auto-resolve.
6. Expired or revoked sessions keep the queue, send nothing, ask for sign-in, and resume only for the same user (A24).
7. Logout with unsynced operations warns first; account switch follows §3.3; both are tested (A26).
8. Two tabs never send the same operation concurrently.
9. Display shows saved and queued state apart, with three statuses only; "Next" and quick call follow the effective view.
10. Rerouting remains disabled offline and queues nothing (A25).

**Tests.**
- API: duplicate, replayed-after-admin-edit, reused id, wrong owner (404 not 403), reassigned, stale version, forbidden transition; a **concurrency** test with two parallel identical operations (one winner, one replay) in the style of `test_concurrency.py`; the 3B lock order is kept; ledger rows hold no customer fields; no customer fields in logs; migration up/down/up.
- Vitest: outbox state machine, per-order chaining and holding, `effectiveView` for every status path, recovery of `sending`, quota failure, drain-then-refresh.
- Playwright (FastAPI-served, killable server): offline taps then reconnect, repeated reconnect, lost-response (kill the server between request and response using a gated test app), admin edit conflict, session expiry mid-queue, account switch with a non-empty outbox, two tabs, reload with a non-empty outbox.
- Pilot-style reconciliation helper: counts of queued, applied, replayed, rejected (the `10-Pilot.md` "offline update integrity" measure), with no customer data.

**Stopping point.** Offline writes proven in the three layers; owner phone check of A22 to A25 (owner-reported). 5C waits.

### 5C: Privacy cleanup, security verification and deployment, backup and restore preparation

**Scope.** Retention that actually runs, the pre-pilot security checks, and a rehearsed runbook. **Nothing is deployed.**

**Depends on:** 5B reviewed (retention must cover `status_operations`). Q5-4 to Q5-7 answered or their defaults accepted. Q5-1 informs the runbook but does not block it.

**Files and schema (proposed).**
- Migration `0008_phase5c_retention` (additive): `delivery_rounds.purged_at`. `routewise_api/retention.py`; `purge` command in `cli.py`; session, login-failure and import-preview sweepers; `tests/test_retention.py`.
- Scripts: `scripts/backup.sh`, `scripts/restore-check.sh` (scratch database only); CI job for the FastAPI-served browser suite in `.github/workflows/ci.yml` (actions pinned by SHA as today).
- Docs: `docs/phase5/DEPLOYMENT-RUNBOOK.md`, `BACKUP-RESTORE.md`, `SECURITY-VERIFICATION.md`, `HOSTING-DECISION.md` (options, evidence, the open decision), `STEP-5C-REPORT.md`; `docs/SECURITY-REVIEW.md` addendum rather than an edit of the 19 Oct record.

**Acceptance criteria.**
1. After a purge, no planted customer string remains in any table column or JSON field, in a data-only dump, or in logs; statuses, counts, timestamps and routes remain; a second run changes nothing; `--dry-run` writes nothing.
2. Rounds younger than the retention period, and rounds with activity inside it, are untouched.
3. A restore onto a scratch database followed by the purge leaves no purged data; the restore and the rollback are rehearsed and timed, with the SW kill switch.
4. The security checks named in [Privacy](../source/notion/RouteWise/07-Privacy.md) ("role isolation, logout/account switching, backup restoration, secure cookies, upload limits and resolver protections") each have a recorded result, automated where possible; failures are recorded honestly in the acceptance cases.
5. A production-configuration checklist is verified locally: `ROUTEWISE_ENV=production` refuses to start without Secure cookies and sets HSTS; docs and OpenAPI are off; the client address used for login throttling is correct behind a proxy (the open note in SECURITY-REVIEW); one API process per database; only the intended port is exposed.
6. Migrations `0007` and `0008` are additive, so the previous app build runs on the new schema; the rollback procedure says when a database restore is needed instead.
7. The hosting decision record states what is verified and what is not, and what the owner must choose.

**Tests.** Retention sentinel scan across the whole schema (via `information_schema`, so a column added later is covered); idempotence; clock-injected age boundaries; sweeper behaviour; backup/restore round trip on scratch; production-mode startup checks; header regression; dependency audits unchanged. Dependency updates, if any, stay in separate commits.

**Stopping point.** Retention, verification evidence and a rehearsed runbook exist locally. The owner chooses a host and approves any deployment. 5D does not start without that choice.

### 5D: Real-device acceptance, human-approved delivery pilot and release review

**Scope.** Deployment to the owner-approved host (if any), device acceptance, the pilot, and the release decision. Mostly human work.
- *5D-1 Staging:* deploy the tagged build to the approved host over HTTPS with the runbook; run restore and rollback there (A27).
- *5D-2 Device acceptance:* A22 to A27 on the supported devices, from the deployed HTTPS origin, including airplane-mode reopen, repeated reconnect, expiry, account switching and a rider whose session expired mid-queue. Owner-reported, apart from automated evidence.
- *5D-3 Pilot:* a small, consenting, owner-approved round measured as in [Pilot](../source/notion/RouteWise/10-Pilot.md). Stop immediately for a wrong destination, unauthorized data exposure or status loss; record, fix and retest.
- *5D-4 Release review:* a checklist against the Phase 5 gate, then the owner's sign-off.

**Depends on:** 5C, the owner's host and device decisions (Q5-1, Q5-2), pilot parameters (Q5-10).

**Files.** `docs/phase5/PHONE-TEST-GUIDE.md`, `PHONE-TEST-RESULTS.md`, `PILOT-PLAN.md`, `PILOT-RESULTS.md`, `RELEASE-REVIEW.md`, `OWNER-ACCEPTANCE-<date>.md`. Real customer data never enters Git or Notion; pilot records use pseudonymous round and rider ids and aggregates.

**Acceptance criteria.** The Phase 5 gate in §1: no lost or duplicate accepted updates; no offline reoptimization claim; security regressions pass; actual pilot observations (no fabricated savings); deployment, restore and rollback evidence; owner sign-off. Production readiness is claimed only if the owner signs it.

**Stopping point.** The owner decides: accept Phase 5, extend the pilot, or send work back.

## 5. Decisions the owner may want to make

None blocks 5A. "Needed by" is the latest useful point.

| # | Question | Proposed default | Needed by |
|---|---|---|---|
| Q5-1 | ₹0 pilot host and HTTPS hostname (§3.8) | Evaluate the owner's machine behind a stable tunnel name first, then an Oracle Arm VM. Decide after 5C | Before 5D |
| Q5-2 | Rider devices and browsers the pilot must support | Android Chrome required (the one tested). iPhone Safari best-effort and not accepted unless riders use it: iOS limits script-writable storage for sites not added to the home screen, and has no Background Sync (not verified here; 5D would test it) | Before 5D |
| Q5-3 | Version conflicts: strict, or auto-apply when the status the rider saw is unchanged and not Completed | **Strict**, with *Apply to the latest* as one tap; measure how often it happens in the pilot | 5B |
| Q5-4 | What starts the 30-day clock for a round | 30 days after the round's last activity | 5C |
| Q5-5 | Purge by anonymizing in place, or delete rows | Anonymize (keeps pilot metrics) | 5C |
| Q5-6 | Backup retention, where backups live at ₹0, encryption | Daily, 14 days, encrypted off-host; worst-case customer-detail lifetime 44 days. Shorter is possible | 5C |
| Q5-7 | Rider Home/Custom coordinates: same 30 days, and not stored on the device | Yes to both | 5C |
| Q5-8 | A previous user's unsynced operations when another user signs in on the device | Keep them (no customer fields) until that user signs in or someone discards them after a warning | 5B |
| Q5-9 | Extra app lock (PIN) over the offline snapshot | No. Device lock only; the snapshot is plaintext on the device for up to 18 hours (§6) | 5A |
| Q5-10 | Pilot size, riders, baseline and success thresholds | Owner supplies, from real operational data ([Pilot](../source/notion/RouteWise/10-Pilot.md)) | Before 5D |
| Q5-11 | Updates: prompt or automatic | Prompt; applies on the next launch | 5A |
| Q5-12 | Which rounds go into the snapshot | Rounds with a Pending or Postponed order for the rider, newest 3 | 5A |
| Q5-13 | Install name, colour and icons | Plain placeholder icons; owner supplies artwork later | 5A |

## 6. Risks and limits (stated, not hidden)

- **Offline writes reach the server only when the app is next open and online.** A rider who closes the app offline and does not reopen it leaves changes waiting. The banner and count are the mitigation; Background Sync would only partly help (Chromium).
- **Browser storage can be evicted or cleared**, silently losing queued operations. `persist()` lowers the chance and does not remove it; 5D measures it.
- **The offline snapshot is plaintext in the browser's storage** for up to 18 hours. Encrypting it with a key kept in the same origin would add little. The protections are the device lock, the 18-hour limit, logout/switch deletion and the minimized contents.
- **Device clocks can be wrong.** Expiry uses the device clock with a clock-back heuristic; it is not a defence against someone who controls the device.
- **No offline login and no offline reroute.** A first visit offline cannot work.
- **Cached shell and API skew.** Handled by the one-release compatibility rule and update prompt, but a rider with a very old shell can be told to update.
- **Single-device evidence.** One phone, Chrome, USB/localhost so far. No iPhone, no HTTPS, no other Android.
- **No hosting option is proven at ₹0**, and a custom domain or IP certificate path is unverified (§3.8).
- **Backups lengthen the real retention period** (§3.6). Retention is not complete until backups and restores are covered.
- **The 4D backend failure is still unexplained.** It is not tied to Phase 5, but CI results are read with that in mind.
- **Process:** the Playwright FastAPI suite is not in CI until 5C; before then browser evidence is local.

## 7. Requirement and case coverage

| Item | Where |
|---|---|
| R21, P5-01, A22 | 5A (read), 5B (queue) |
| R16, R21, P5-02, A23 | 5B |
| R21, R24, A24 | 5B (expiry, reauthentication, conflict) |
| R22, P5-03, A25 | Kept from 4D; re-tested in 5A and 5B |
| R24, A26 | 5A (snapshot, switch), 5B (warning with an outbox) |
| R02, R24, P5-04, A27 | 5C (rehearsal), 5D-1 (on the real host) |
| A28, R01 to R24 | 5D |
| D09 values | 5A, 5B |
| D10 values | 5C |

## 8. The first implementation prompt (5A) should say exactly this

> Implement step 5A of `docs/phase5/IMPLEMENTATION-PLAN.md` on a new branch from `main`, in two commits: (1) the offline app shell, (2) the expiring own-rider read-only snapshot. Offline is read-only: no queue, no offline writes, no schema change, no migration. No new runtime dependency. Do not start 5B, retention, deployment or hosting work; do not touch Notion, `docs/source/` or `routewise_phone`; do not start servers other than what the browser tests need, and stop any you start.
>
> Defaults to use unless I change them: Q5-9 no PIN; Q5-11 update prompt, applied on next launch; Q5-12 rounds with a Pending or Postponed order for the rider, newest 3; Q5-13 placeholder icons.
>
> First, verify in a short spike and record: whether Playwright 1.63 `setOffline` reaches service-worker requests (if not, the spec uses its own killable FastAPI process); and that a same-origin worker is allowed by the current CSP.
>
> Deliver the acceptance criteria and tests listed under 5A, a `docs/phase5/STEP-5A-REPORT.md` with evidence (automated and mocked-network kept apart from anything owner-reported), updated `docs/DEVELOPMENT.md` (including that airplane mode does not cut an `adb reverse` tunnel), and the narrowed `expectNoBrowserStorage`. Run the affected suites once; do not repeat full-suite loops. Commit each part, push the branch, open a draft PR, report its checks, and stop for review. Do not merge.
