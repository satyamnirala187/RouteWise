# Privacy and security

[Home](../RouteWise.md)

These are implementation requirements. No security checks have been executed yet.

- Enforce Admin/Rider permissions and order ownership on the server. Riders receive only their assigned orders and their own endpoint.
- Use secure, revocable sessions, modern password hashing, login throttling and CSRF protection. Keep credentials out of frontend bundles and documentation.
- Encrypt transport with HTTPS. Restrict database credentials and provider keys. Redact contacts, precise coordinates, home destinations and session tokens from logs and QA evidence.
- Request current location only for the rider action that needs it. Offer the explicit last-completed-stop fallback. Continuous rider tracking is outside scope.
- Cache only the authenticated rider's minimum saved data. Partition local storage by account. Clear sensitive snapshots on logout/account change under the agreed unsynced-operation policy.
- Set documented retention and expiry periods during Phase 0. Do not promise indefinite offline availability or retention without a decision.
- Resolve map links through an allowlist with redirect limits, timeouts and private-network rejection. Do not fetch arbitrary user-provided URLs.
- Validate upload types, sizes and rows; do not execute spreadsheet formulas/macros. Treat imported text as untrusted display content.
- Protect queued status updates with operation IDs, authorization and version checks. Session expiry requires reauthentication before sync.
- Restrict Notion/GitHub documentation to project material and synthetic fixtures. Real customer data belongs in the authorized application environment.

Before a pilot, check role isolation, logout/account switching, backup restoration, secure cookies, upload limits and resolver protections. Record failures honestly in Acceptance cases.
