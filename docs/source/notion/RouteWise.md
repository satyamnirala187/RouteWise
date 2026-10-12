# RouteWise | Development

**A practical delivery workspace for a small startup**

> **Current status — 12 October 2026:** Planning documents prepared. Phase 0 is next and has not started. Implementation phases complete: **0 of 6**. This page is a local import template until imported into Notion.

## What we are building

A mobile-first Progressive Web App for an admin and scooter/bike delivery riders. The admin imports customer orders from Excel, reviews locations, configures riders and creates efficient road-based routes. Riders choose their own final destinations, see only their assigned deliveries, call customers, open Google Maps and update orders.

The product should reduce daily planning effort and help riders handle unavailable customers without changing who holds other riders' packages. Route quality and usability will be measured in a small real-delivery pilot; no performance claims have been proved yet.

## How it works

**Admin login → Excel upload → review/correct orders and pins → configure riders, capacities and Office/Warehouse starts → each rider confirms their endpoint → admin optimizes all routes → riders call, navigate and deliver → individual rerouting when needed → offline updates sync after reconnect.**

Order statuses are exactly **Pending / Postponed / Completed**. Same-building orders share a navigation stop while keeping separate customer records and statuses. A rider reroutes only their remaining assigned deliveries. Online connectivity is required for reoptimization.

[View the screen-by-screen workflow](RouteWise/02-Working-Flow.md)

## Tech stack and decisions

| Layer | Working choice | Decision state |
|---|---|---|
| Development | Mac, Cursor, Claude Code | Selected workflow; Cursor observed running and Claude Code CLI verified locally |
| Frontend | React, TypeScript, Tailwind, mobile-first PWA | Proposed implementation baseline; versions not locked |
| Backend | FastAPI/Python | Proposed; isolated environment to be created |
| Data | PostgreSQL | Proposed; schema and migrations pending |
| Route optimization | OR-Tools + real road-distance matrix API | Candidate architecture; technical spike not run |
| Map display | Leaflet if compatible with selected provider | Pending provider and licensing decision |
| Import | Pandas + openpyxl | Proposed; import prototype pending |
| Authentication | Secure server sessions, Admin/Rider permissions | Required behavior; implementation pending |
| Offline | Saved own-rider list + queued status updates | Confirmed scope; browser tests pending |

[Architecture, verified facts and unresolved choices](RouteWise/03-Architecture.md)

## Project current status

| Phase | Outcome | Status |
|---|---|---|
| 0 | Architecture and real-road routing spike | Not started |
| 1 | Foundation, secure login and Excel import | Not started |
| 2 | Routing and multi-rider constraints | Not started |
| 3 | Rider screens, call, navigate and status | Not started |
| 4 | Quick call, individual rerouting and same-building grouping | Not started |
| 5 | Offline PWA, tests, real-delivery pilot and deployment | Not started |

**Next action:** Execute the Phase 0 kickoff and record real routing results. **Gate:** do not start Phase 1 until the Phase 0 evidence is reviewed. **Open dependencies:** provider credentials/spend approval when needed, service area and real pilot sample. Public test locations can support early experiments without private customer data.

This summary is a dated snapshot. After Notion import, replace the phase table with a linked view of the Phases database to avoid duplicate status editing.

## Track the work

- [Phases database import](RouteWise/Phases.csv)
- [Tasks database import](RouteWise/Tasks.csv)
- [Acceptance cases database import](RouteWise/Acceptance-Cases.csv)
- [Decisions database import](RouteWise/Decisions.csv)
- [Tracker views and property setup](RouteWise/05-Notion-Setup.md)

## Project library

- [Product vision and scope](RouteWise/01-Product.md)
- [Working flow](RouteWise/02-Working-Flow.md)
- [Architecture and tech stack](RouteWise/03-Architecture.md)
- [Roadmap and milestone gates](RouteWise/04-Roadmap.md)
- [Testing and acceptance criteria](RouteWise/06-Acceptance.md)
- [Privacy and security](RouteWise/07-Privacy.md)
- [Decision log](RouteWise/08-Decisions.md)
- [Change log and phase update protocol](RouteWise/09-Updates.md)
- [Real-delivery pilot](RouteWise/10-Pilot.md)
- [Official reference sources](RouteWise/11-Sources.md)

## Project links

| Destination | Link/status |
|---|---|
| New ChatGPT Project | Not created; add verified URL after creation |
| Notion home | Not created; add verified URL after import |
| GitHub repository | Not created |
| Demo | Not deployed |
| Latest QA evidence | No application QA executed |

## Working agreement

Use phases, test before marking complete, and publish a concise Notion update after human review. Keep credentials and real customer data out of project documents. ChatGPT does not automatically synchronize this workspace. No update automation is enabled.
