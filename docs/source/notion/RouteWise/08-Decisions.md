# Decision log

[Home](../RouteWise.md)

| ID | Decision | State | Choice / next action |
|---|---|---|---|
| D01 | Product scope | Confirmed requirement | Requirements R01–R24; only selected add-ons 2/4/8/9 |
| D02 | Development environment | Selected for kickoff | Mac + existing Cursor + Claude Code terminal |
| D03 | Application stack | Proposed | React/TypeScript/Tailwind, FastAPI, PostgreSQL, Pandas/openpyxl |
| D04 | Road matrix and map provider | Pending | Trial coverage, motorbike profile, limits, cost, display and cache rights |
| D05 | Priority semantics | Proposed | First active order on its assigned rider route; report conflicts |
| D06 | Capacity units | Proposed | Order count; grouped stops retain underlying order demand |
| D07 | Distribution objective | Proposed | Equal count subject to constraints; smart road-cost minimization; manual fixed assignment |
| D08 | Postponed return | Proposed | Remains assigned; excludes from active route until explicitly returned to Pending |
| D09 | Offline conflict/expiry policy | Pending | Idempotent operation replay, version reconciliation, cache/session expiry and logout behavior |
| D10 | Deployment and retention | Pending | Hosting, backup policy, domain, data retention and approved spend |
| D11 | Package assignment preservation | Confirmed requirement | Rider reroutes preserve other riders' packages; no compulsory confirmation stage |

Each decision page should contain context, considered options, evidence, choice, consequences, owner and review date. Pending decisions have no invented approval dates. Reopen a decision when real spike evidence contradicts its assumption.
