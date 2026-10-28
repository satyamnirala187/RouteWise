# Phase 4 — accepted for local development

**Owner approval:** 28 October 2026. The owner approved Phase 4 (quick call, rerouting and shared stops) **for local development** and authorized merging PR #10 into `main`. Phase 5 has **not** been started; it starts only when the owner asks. This is **not** production acceptance.

**Commit:** the commit that adds this record. It sits on top of:
- 4A `e40e0b0`, 4B `e06e31c`, 4C `8336ed0` (with `1cab378`, a phone-database test fix) and 4D `3838f98`, on Phase 3 (accepted at `3fa1e40`);
- `b908f6d` (earlier dependency-audit fix);
- PR #10: the geolocation fix `2ac1e5e`, the owner-reported phone results `6ef7a93` and the dependency fixes `471d901`.

PR #10 is merged with a merge commit, so these commits keep their history. The merge commit and the check results are shown by GitHub for the PR and are not recorded in this file. Nothing is deployed.

## What the acceptance rests on

The two kinds of evidence are kept separate.

1. **Automated evidence**, as recorded in the step reports ([4A](STEP-4A-REPORT.md), [4B](STEP-4B-REPORT.md), [4C](STEP-4C-REPORT.md), [4D](STEP-4D-REPORT.md), including the 4D correction pass) and in [GEOLOCATION-POLICY-FIX.md](GEOLOCATION-POLICY-FIX.md): backend and unit tests, browser tests at two widths, and the browser regression that serves the built app from FastAPI. **Every automated GPS position is mocked geolocation**; no automated test used a real device position. CI, the dependency audits and CodeQL passed on PR #10's final head before the merge (see GitHub).
2. **Owner-reported Android phone results** in [PHONE-TEST-RESULTS.md](PHONE-TEST-RESULTS.md), on a OnePlus Nord 5 with Chrome over USB/localhost: Office and last-completed-stop reroutes, Postpone, destination change, offline behaviour, **real Android GPS rerouting after the Permissions-Policy fix**, the shared-stop checks and the blocked-location fallback. These are the owner's own reports. They were not automated, and no one else observed them.

## Accepted scope

- **4A:** next-customer quick call, and "Customer unavailable" as Postpone.
- **4B:** rider route revisions on immutable round plans (`routewise_api/reroute.py`, migration 0005), explicit origins, a rider's own destination recalculation.
- **4C:** same-building stop grouping (migration 0006): exactly identical resolved pins, explicit admin confirmation, admin controls on the Orders page.
- **4D:** the rider screens: "Recalculate my route" with explicit, never-preselected origins; a one-shot device position that is never stored; safe run handling; shared-stop containers with one Navigate per stop; the Route card and the admin plan page reading the effective rider route; `scripts/phone-server.sh localhost` for a USB/`adb reverse` test.
- **Defect fix (PR #10):** the API sent `Permissions-Policy: geolocation=()`, which blocked location even on `http://localhost:8020`. It is now `geolocation=(self), camera=(), microphone=()`, a document-policy block is worded as a block and not as the rider's refusal, and a FastAPI-served browser regression covers it.
- **Dependency fixes (PR #10):** `vitest` 5.0.3 (direct) and the transitive `undici` 8.12.3 (lockfile only) for the published advisories; the CI audit threshold is unchanged.

## Local development only

This is **not** production acceptance. Not performed:
- deployment, HTTPS or backups;
- iPhone/Safari, Firefox or other Android devices and browsers (one phone, Chrome, USB/localhost only);
- location over the Wi-Fi address or HTTPS (the app correctly reports location as unavailable on the plain-HTTP Wi-Fi address);
- a screen-reader pass, load testing, or a full delivery round on a phone;
- offline page loading: the owner saw Chrome's offline page on a refresh while offline. This is Phase 5, not a Phase 4 defect.

## Not supplied or not reported (left open, not inferred)

Android and Chrome versions, the commit tested, the test time, GPS accuracy and indoor/outdoor conditions, Wi-Fi-mode location text, that another rider was unaffected by the destination change, touch and readability, and the wording shown for the blocked-location fallback. See [PHONE-TEST-RESULTS.md](PHONE-TEST-RESULTS.md).

## Still open (not decided by this approval)

- **Provisional decisions stay provisional:** the 4B GPS limits (100 m, 60 s), no manual position entry, priority stays first, round-wide admin edits and refusing reroutes during an admin optimization (Q4-2, Q4-3, Q4-4, Q4-5, Q4-7); the 4C exact-pin grouping rule (Q4-1). They are local implementation defaults, not approved permanent product decisions. Whether the USB/localhost route is the approved real-phone route (Q4-6) is not decided by this approval either.
- **Phase 2 proposals Q1–Q8** remain pending. The Q1 "all orders Pending" replanning restriction is not built and must not be built without approval.
- **Unexplained backend failure:** the first full backend run at the 4D checkpoint had one failure that is still **unidentified and unreproduced** ([4D report §3.2](STEP-4D-REPORT.md)). Two complete reruns passed; nothing in this approval or in PR #10 explains it.
- **Limitations** listed in each step report stay open (for example the 4B/4C items in their reports and the 4D "Remaining limitations").
- **Production readiness** is pending. **Phase 5** (including offline use) has not started.
- **Roadmap and tracker:** `docs/source/` is a verbatim copy and is not edited, so the roadmap's own wording is unchanged; the status lives in this record and in the README files. Notion was not accessed and no tracker update was prepared or applied.
