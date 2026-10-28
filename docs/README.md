# Documentation index

## Source package (verbatim copy, do not edit)

Copied on 12 October 2026 from the RouteWise development package. The copies are byte-identical to the originals, and the originals were not modified (SHA-256 checksums matched before and after Phase 0 work). Not copied: the ZIP bundles, ChatGPT project seed files and Notion QA screenshots, which are not needed for development.

- [START-HERE](source/START-HERE.md) · [Home](source/notion/RouteWise.md)
- [Product](source/notion/RouteWise/01-Product.md) · [Working flow](source/notion/RouteWise/02-Working-Flow.md) · [Architecture](source/notion/RouteWise/03-Architecture.md) · [Roadmap](source/notion/RouteWise/04-Roadmap.md)
- [Acceptance](source/notion/RouteWise/06-Acceptance.md) · [Privacy](source/notion/RouteWise/07-Privacy.md) · [Decisions](source/notion/RouteWise/08-Decisions.md) · [Updates protocol](source/notion/RouteWise/09-Updates.md)
- [Mac setup](source/development/MAC-SETUP.md) · [Kickoff](source/development/KICKOFF.md)
- Tracker CSVs: [Phases](source/notion/RouteWise/Phases.csv), [Tasks](source/notion/RouteWise/Tasks.csv), [Acceptance cases](source/notion/RouteWise/Acceptance-Cases.csv), [Decisions](source/notion/RouteWise/Decisions.csv)

## Security

- [Security review before publication](SECURITY-REVIEW.md) (19 Oct 2026) and the [security policy](../SECURITY.md). The repository is public; the app is not deployed or production-ready
- [Security follow-up: dependency-audit failures, 22 Oct 2026](security-followup/2026-10-22-dependency-audit.md): the findings, the exact `vite` and `certifi` updates, validation and the original failed CI logs (kept as historical evidence).

## Phase 4 (accepted 28 Oct 2026 for local development)

- [Owner acceptance record](phase4/OWNER-ACCEPTANCE-2026-10-28.md): accepted for local development, **not** production readiness; owner-reported phone results are kept separate from the automated (mocked-geolocation) tests; limitations, provisional decisions and the unreproduced backend failure stay open
- [Owner-reported phone results](phase4/PHONE-TEST-RESULTS.md) (OnePlus Nord 5, Chrome, USB/localhost, including real Android GPS) and the [geolocation policy fix](phase4/GEOLOCATION-POLICY-FIX.md)
- [Implementation plan](phase4/IMPLEMENTATION-PLAN.md): 4A quick next-customer call, 4B individual rerouting and endpoint-change recalculation, 4C same-building stops, 4D integration and device verification; rider route revisions on top of round plans. The owner authorized 4A, 4B and 4C, each on its own; 4B uses provisional defaults for Q4-2/3/4/5/7 and 4C a provisional grouping default for Q4-1; Q4-6 is pending
- [Step 4A report](phase4/STEP-4A-REPORT.md): next-customer quick call and "Customer unavailable" (Postpone). Committed (`e40e0b0`); accepted with Phase 4
- [Step 4B report](phase4/STEP-4B-REPORT.md): rider route revisions on immutable round plans, explicit origins, rider-only destination recalculation (API; screens in 4D). Committed (`e06e31c`); accepted with Phase 4; GPS limits and related values are provisional defaults
- [Step 4C report](phase4/STEP-4C-REPORT.md): same-building stop grouping: admin-confirmed groups of orders with exactly identical pins, one stop per applicable rider in admin plans and rider reroutes, admin controls on the Orders page, shared-stop metadata in the rider API. Committed (`8336ed0`); accepted with Phase 4; the grouping rule is a provisional local default; the rider's shared-stop screens arrived in 4D
- [Step 4D report](phase4/STEP-4D-REPORT.md): the rider screens for individual rerouting and shared stops: "Recalculate my route" with explicit origins (current location, last completed stop, configured start), safe handling of runs and unknown outcomes, one Navigate per shared stop, the Route card and admin plan page reading the effective rider route, and a localhost mode in `scripts/phone-server.sh` for a later USB GPS test. Committed (`3838f98`); accepted with Phase 4; browser GPS tests are mocked geolocation, real-phone results are owner-reported ([record](phase4/PHONE-TEST-RESULTS.md)); production readiness and Phase 5 are pending.

## Phase 3 (accepted 19 Oct 2026 for local development)

- [Owner acceptance record](phase3/OWNER-ACCEPTANCE-2026-10-19.md)
- [Phase 3 report](phase3/PHASE3-REPORT.md): 3A + 3B summary, evidence, acceptance criteria, delivery-card polish
- [Real-phone test guide](phase3/PHONE-TEST-GUIDE.md) and [results](phase3/PHONE-TEST-RESULTS.md): owner-reported device results (OnePlus Nord 5, Chrome); functional checks on the original UI, visual check of the polished cards
- [Step 3A report](phase3/STEP-3A-REPORT.md): rider delivery view, call and Google Maps navigation links (read-only). Committed (`2b52cbc`)
- [Step 3B report](phase3/STEP-3B-REPORT.md): riders' own delivery-status updates, progress versus route validity. Committed (`e2139c1`)

## Phase 2 (accepted 19 Oct 2026 for local development, `41b37f8`)

- [Owner acceptance record](phase2/OWNER-ACCEPTANCE-2026-10-19.md)

- [Implementation plan: steps 2A, 2B, 2C](phase2/IMPLEMENTATION-PLAN.md)
- [Step 2A report](phase2/STEP-2A-REPORT.md): rider setup, depots, destinations, confirmations, readiness. Committed (`13de782`)
- [Step 2B report](phase2/STEP-2B-REPORT.md): local Valhalla + OR-Tools planning, runs, versioned plans. Committed (`9c0db08`)
- [Step 2C report](phase2/STEP-2C-REPORT.md): configuration and planning screens, rider destination card, browser verification, with its correction pass. Committed (after `9c0db08`)
- [Phase 2 report](phase2/PHASE2-REPORT.md): requirement-to-evidence checklist (written before the approval)

## Phase 1 (accepted 13 Oct 2026 for local development, `fcac55e`)

- [Owner acceptance record](phase1/OWNER-ACCEPTANCE-2026-10-13.md)
- [Phase 1 report](phase1/PHASE1-REPORT.md): start here
- [Local development guide](DEVELOPMENT.md)

## Phase 0 outputs (accepted 13 Oct 2026)

- [Owner acceptance record](phase0/OWNER-ACCEPTANCE-2026-10-13.md)
- [Phase 0 report](phase0/PHASE0-REPORT.md)
- [Acceptance results](phase0/ACCEPTANCE-RESULTS.md)
- [Local Valhalla evaluation — DU North Campus, ₹0](phase0/VALHALLA-LOCAL.md)
- [Provider comparison (₹0 correction)](phase0/PROVIDER-COMPARISON.md) · [Stadia suitability (inactive)](phase0/STADIA-SUITABILITY.md)
- [Provider evaluation and cost (12 Oct, pre-budget)](phase0/PROVIDER-EVALUATION.md)
- [Architecture decision record](phase0/ARCHITECTURE-DECISION.md)
- [Offline and privacy proposal](phase0/OFFLINE-PRIVACY.md)
- [Environment and reproduction](phase0/ENVIRONMENT.md)
- [Proposed Notion update (not applied)](phase0/NOTION-UPDATE-PROPOSAL.md)
