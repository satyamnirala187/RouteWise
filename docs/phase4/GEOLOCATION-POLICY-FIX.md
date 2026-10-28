# Geolocation blocker found in the real Android phone test — fix and evidence

Status: fix implemented on branch `fix/geolocation-permissions-policy`, **not merged**. This is a defect fix for step 4D. It does not accept Phase 4:
Phase 4 is incomplete. After the fix, the owner reported real Android GPS rerouting working and the shared-building checks passing ([owner-reported results](PHONE-TEST-RESULTS.md)).

## Root cause

`services/api/routewise_api/main.py` added `Permissions-Policy: geolocation=(), camera=(), microphone=()` to every response, the
HTML document included. An empty allowlist `geolocation=()` disables location for the document for every origin, `http://localhost:8020` too. The
phone server and the `adb reverse` route were correct (a loopback page is a secure context); the document policy blocked location before the
browser could ask the rider. Chrome reports such a block through the same error code as a refused permission (`PERMISSION_DENIED`).

## Fix

- Header is now `geolocation=(self), camera=(), microphone=()`: location only for the app's own origin; camera and microphone stay blocked; no
  wildcard. The other security headers, authentication, CSRF and origin restrictions are unchanged. No browser flag or certificate bypass is involved.
- Location error wording (`apps/web/src/reroute.ts`):
  - Where the browser says so (`document.permissionsPolicy`, formerly `featurePolicy`, `allowsFeature("geolocation")`), a document-policy block is a
    separate problem, `blocked`: "This page's own security settings block location, so your browser never asked you. That is not a choice you
    made…". It is detected before asking, so nothing is requested. The location button stays disabled and the other starting points stay available.
  - An error code 1 elsewhere is no longer worded as the rider's own refusal. It now says the browser did not allow location for this page, and lists
    the possible causes (the browser's question, a site or phone setting, a block by the page that cannot be told apart here).
  - A browser that does not expose the policy API is treated as "not known to be blocked".

## Tests

- Backend (`services/api/tests/test_permissions_policy.py`): the real HTML documents FastAPI serves (a temporary build), including `/`, `/index.html`
  and SPA deep links, carry exactly `geolocation=(self), camera=(), microphone=()` and every other security header; assets and API responses carry the same policy.
- Frontend unit tests (`reroute.test.ts`, `useReroute.test.tsx`): `blocked` vs `denied`, no browser call when the page blocks location.
- Browser regression (`apps/web/e2e/fastapi-geolocation.spec.ts`, config `playwright.fastapi.config.ts`): rebuilds the web app, serves it from FastAPI alone
  on `http://localhost:8021`, as `scripts/phone-server.sh` does, and checks in Chrome that the document header is right, the page's own policy allows
  location and still blocks camera and microphone, `getCurrentPosition` is the browser's native function (never replaced), and tapping "Use my
  current location" sends a reroute that the server accepts (202) and saves as a current-position revision.
  **This is mocked geolocation, not real-phone GPS**: Playwright grants the permission and emulates a public test point in the DU North Campus fixtures.
  Run: `scripts/e2e.sh -c playwright.fastapi.config.ts` (isolated `routewise_e2e` database; `routewise_phone` is not touched).
- Regression demonstration: with the old `geolocation=()` header put back temporarily, the spec failed twice. First on the header assertion
  (`Received: "geolocation=(), camera=(), microphone=()"`). Then, with that one assertion switched off, on the browser's own answer
  (`location: false` where `true` was expected). The fix was restored afterwards.

## Why the earlier browser tests missed it (coverage gap)

The existing Playwright specs run the app through the Vite dev server (`localhost:5174`, `/api` proxied). Vite serves the HTML, so FastAPI's
`Permissions-Policy` header never reached the page, and Playwright's granted permission was enough for emulated geolocation to answer. The
phone launcher serves the built app from FastAPI, a path no browser test exercised. The new spec covers it.

## Still open

Phase 4 acceptance (the owner's decision). The phone results are owner-reported only; the automated regression above is mocked geolocation. Plan
proposals Q1–Q8 and the provisional 4B/4C defaults stay open.
