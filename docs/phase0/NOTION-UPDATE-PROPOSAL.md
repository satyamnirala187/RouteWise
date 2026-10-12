# Proposed Notion progress update — FOR REVIEW, NOT APPLIED

**Notion has not been updated.** This is a proposed diff for the existing records in the live workspace (Phases, Tasks, Acceptance cases, Decisions, home page). Per [09-Updates](../source/notion/RouteWise/09-Updates.md), apply it only after the owner approves the Phase 0 report, edit existing rows (do not re-import CSVs), and re-read the changed records afterwards.

Evidence links below are repository-relative. Replace them with GitHub URLs once a repository exists; none has been created. The Commit field stays blank until a commit exists.

## Phases

| ID | Field | Current | Proposed |
|---|---|---|---|
| P0 | Status | Not started | **In progress** |
| P0 | Start date | — | 2026-10-12 |
| P0 | QA evidence | — | `docs/phase0/ACCEPTANCE-RESULTS.md` |
| P0 | Decision link | — | `docs/phase0/ARCHITECTURE-DECISION.md` |
| P0 | Human approval | — | *(blank until sign-off)* |
| P1–P5 | — | Not started | *(no change)* |

## Tasks

| ID | Status: current → proposed | QA evidence | Notes (proposed) |
|---|---|---|---|
| P0-01 | Not started → **In review** | `docs/phase0/ENVIRONMENT.md` | Python 3.14.3 venv, pinned lock, clean-checkout run passed; local Git initialised, no commit yet |
| P0-02 | Not started → **Blocked** | `spikes/routing/evidence/osrm_live_capture.json`, `google_routes_check.json` | Real OSRM road matrix captured (car proxy, asymmetry shown). Google TWO_WHEELER trial blocked: no key or spend approval |
| P0-03 | Not started → **In review** | `ACCEPTANCE-RESULTS.md` criteria 3–4 | All 5 endpoints; gate at API (409) |
| P0-04 | Not started → **In review** | criteria 5–6 | Equal/smart/manual, locks, capacity, priority conflicts |
| P0-05 | Not started → **In review** | criteria 7–8 | Rider-only reroute; shared stops keep independent statuses |
| P0-06 | Not started → **In review** | criterion 10 | Live short-link check not run (no sample link) |
| P0-07 | Not started → **In progress** | `PROVIDER-EVALUATION.md`, `OFFLINE-PRIVACY.md` | Costs and policies recorded; D04/D09/D10 need owner decisions |
| P0-08 | Not started | — | *(no change until review)* |

For every changed task, also set Start date 2026-10-12 and Owner: Claude Code (implementation), with the human reviewer added at sign-off.

## Acceptance cases

| ID | Result: current → proposed | Evidence | Tester | Run date |
|---|---|---|---|---|
| A01 | Not run → **Blocked** | OSRM real-road check passed; Google two-wheeler trial blocked (criterion 2 row) | Claude Code (automated) | 2026-10-12 |
| A02 | Not run → **Passed** | `test_each_rider_starts_and_ends_where_requested` | Claude Code (automated) | 2026-10-12 |
| A03 | Not run → **Passed** | `test_last_stop_adds_no_artificial_return_trip` | Claude Code (automated) | 2026-10-12 |
| A04 | Not run → **Passed** | criterion 5 tests | Claude Code (automated) | 2026-10-12 |
| A05 | Not run → **Passed** | `test_conflicting_priorities_are_reported_explicitly` | Claude Code (automated) | 2026-10-12 |
| A06 | Not run → **Passed** | `test_matrix_google.py`, `test_matrix_osrm.py`, `test_unreachable_labels.py` | Claude Code (automated) | 2026-10-12 |
| A07–A28 | Not run | — | — | *(no change; spike evidence noted only in task pages)* |

## Decisions

| ID | State: current → proposed | Choice / evidence to add |
|---|---|---|
| D03 | Proposed → Proposed | Python 3.14.3 verified with OR-Tools 9.15.6755, FastAPI 0.143.0, pandas 3.0.6, openpyxl 3.1.5; 3.12 not needed |
| D04 | Pending → Pending | Evidence: India supported for TWO_WHEELER (beta); Enterprise SKU $15 per 1,000 elements after 1,000 free; Routes results must be shown on a Google Map; projections $313/$1,443/$4,465 per month (20/50/100 orders). Next: owner picks the direction and approves a $0-capped 36-element trial |
| D05 | Proposed → Proposed | Implemented and tested; awaiting owner confirmation |
| D06 | Proposed → Proposed | Implemented and tested; awaiting owner confirmation |
| D07 | Proposed → Proposed | Equal = soft count band + warning; smart minimises road distance. Owner to confirm the metric |
| D08 | Proposed → Proposed | Implemented and tested; awaiting owner confirmation |
| D09 | Pending → Proposed | 18 h snapshot expiry, 12 h idle / 7 day sessions, op_id + version replay, logout warning (see `OFFLINE-PRIVACY.md`) |
| D10 | Pending → Pending | Retention 30 days proposed; hosting, domain and spend still open |
| *(new)* D12 | — → Proposed | Optimization as an in-process async task with polling (100 orders ≈ 14 s measured); solver config insertion + GLS, 1,000-solution bound |

## Home page

- Current-status callout: "**Phase 0 in progress (in review).** Routing spike built and tested on real OpenStreetMap road distances (114 automated tests passing). Live Google two-wheeler trial blocked pending credentials and spend approval. Phase 1 not started." Phases complete: **0 of 6**.
- Project links → Latest QA evidence: `docs/phase0/ACCEPTANCE-RESULTS.md` (local; no GitHub repository yet).

## Change log (09-Updates) row

| Date | Change | Evidence / actual completion |
|---|---|---|
| 12 October 2026 | Phase 0 spike executed locally: isolated Python 3.14 environment, OR-Tools routing spike, real OSRM road matrix, provider and cost evaluation, offline/privacy proposal | 114 tests passed, 2 skipped; Google live trial Blocked; awaiting owner review. Not marked complete |
