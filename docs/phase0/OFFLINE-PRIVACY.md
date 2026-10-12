# Offline and privacy architecture (criterion 12, decision D09) — proposal

**State:** proposed design for owner decision. Nothing here is implemented; offline behaviour is Phase 5. Values marked *(proposed)* are not approved.

## What a rider's device may store

| Data | Stored offline? | Notes |
|---|---|---|
| Own assigned orders: customer name, products, contact, instructions, stop sequence, statuses | Yes, in IndexedDB, partitioned by user id | Minimum data needed to deliver while offline (R21) |
| Own stop coordinates | Yes | These are our own data from import or manual pin. If D04 = Google, store only our own coordinates, never Google route geometry or matrix values |
| Road matrix / route geometry from provider | **No** under Google (caching restricted); possible under an ODbL provider | Reoptimization needs connectivity anyway (R22) |
| Own endpoint (Home/Custom) | Yes, own only | Never another rider's endpoint |
| Other riders' data, admin views, full import | **Never** | — |
| Pending status operations (outbox) | Yes, until acknowledged | See queue rules |

The service worker caches only the **app shell**. API responses with customer data are never put into a generic HTTP or Cache Storage cache; they go only into the partitioned IndexedDB snapshot.

## Expiry and logout *(proposed)*

- The snapshot expires **18 hours** after the last successful sync *(proposed; covers one working day)*. After expiry, the list is hidden until re-authentication and sync.
- Server session: **12-hour idle timeout and 7-day absolute lifetime** *(proposed)*. On expiry, queued operations are kept locally but not sent until the rider re-authenticates (R24).
- **Logout with unsynced operations:** warn and offer "Sync now". If the rider confirms logout anyway, the outbox and snapshot are deleted, and the warning states that the unsynced changes will be lost. **Account switch on the same device:** always clears the previous user's partition.
- Customer data must not appear in logs, analytics, crash reports or QA evidence. Logs carry order ids only.

## Status queue and conflicts *(proposed)*

- Each local change creates `{op_id (UUID), order_id, expected_version, from, to, actor, client_time}`. The display updates immediately and shows **waiting to sync** as metadata (not a fourth status).
- On reconnect, the client re-authenticates, then replays the operations in order. The server de-duplicates by `op_id`, so a duplicate returns the original acknowledgement.
- If `expected_version` ≠ the current version, the server rejects the operation and returns the current state, and the UI shows the conflict. **A stale transition never overwrites Completed** (e.g. an older Pending change).
- Server time and authorization decide the accepted state, so device clock drift affects only display ordering.

## Retention (D10) *(proposed, owner to confirm)*

Keep customer contact and address fields on the server for the delivery round plus **30 days** for disputes, then purge or anonymize them. Keep aggregate pilot metrics without personal data. Back up with the same retention.

## Phase 0 checks already in the spike

- Endpoint-gate API errors contain rider ids and reasons, never coordinates (test `test_api_boundary_blocks_until_every_rider_confirms`).
- Provider adapters never echo the API key in error messages (test `test_http_and_payload_failures_raise_typed_errors_without_leaking_key`).
- Fixtures use public landmarks and synthetic names only. `.gitignore` excludes `.env`, spreadsheets, uploads, dumps and private fixtures.
