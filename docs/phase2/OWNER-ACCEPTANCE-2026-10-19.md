# Phase 2 — accepted for local development

Owner approval: 19 October 2026. The owner explicitly approved Phase 2 for local development at the commit below and asked for Phase 3, step 3A, to start.

Commit: `41b37f801bf6b62aa3100a4246d79d9c6f1cc515` (`41b37f8`), "Add RouteWise planning screens and end-to-end verification", on top of 2A `13de782` and 2B `9c0db08`. The same commit is on `main` of the owner's private GitHub repository `RouteWise` (pushed 19 October 2026 with owner authorization). Nothing is deployed.

Accepted scope: Office/Warehouse and per-round rider setup; rider-chosen, separately confirmed destinations with version rules; the readiness gate in UI and API; planning on local Valhalla road distances with OR-Tools in equal, smart and manual modes, owner locks and first-delivery priority; versioned plans with stale-input rejection, recovery and account-deactivation handling; the admin configuration and planning screens, the rider destination card, readiness refresh and serialized mode changes. Evidence and results are as recorded in [PHASE2-REPORT.md](PHASE2-REPORT.md) and the step reports ([2A](STEP-2A-REPORT.md), [2B](STEP-2B-REPORT.md), [2C](STEP-2C-REPORT.md)); this record does not add or re-state test runs.

**Local development only.** This is not production readiness. Not performed: deployment, HTTPS, backups, CI, real phones, Safari/Firefox, a screen-reader pass, load testing. The browser suite runs on recorded real-road matrices with one opt-in flow on the live local tiles.

**Still open (not decided by this approval):**
- Pending owner decisions Q1 (replanning restriction, not built), Q2 (destination change after issue), Q6 (size cap; 80/8/100 set locally), Q7 (snap threshold), Q8 (map display), and whether riders with no orders should be left out of a plan.
- B1: the real Office/Warehouse locations are entered by the owner and never committed.
- The limitations listed in PHASE2-REPORT §5 and STEP-2C-REPORT §8 and §10 (for example equal mode can miss the equal split at larger sizes; the mode endpoint is last-write-wins across admin tabs; no retention purge).

Notion remains paused: no tracker update was prepared or applied with this record. The tracker proposals in PHASE2-REPORT §6 are unchanged and remain for a human to apply.
