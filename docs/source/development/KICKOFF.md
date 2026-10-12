# Claude Code development kickoff

Paste the following into Claude Code after opening the dedicated RouteWise folder in Cursor:

```text
Set up and execute Phase 0 of RouteWise. Read the product, workflow,
architecture, roadmap, privacy, decisions and acceptance documents in this
package first. Treat the consolidated requirements as the scope baseline.

Use Mac + Cursor, React/TypeScript/Tailwind, FastAPI/Python, PostgreSQL,
OR-Tools, a real road-matrix adapter, Pandas/openpyxl and an offline PWA.
These are proposed technical choices until compatibility is checked. Verify
installed tools and isolate dependencies. Do not modify system Python.

Deliver a reproducible routing spike and architecture decision. Use public
test points, at least two riders/eight orders, Office/Warehouse starts,
different fixed ends, Last stop/open routes, capacity, equal/smart/manual
assignment, manual ownership locks and first-delivery priority. Validate
all five endpoint options. Initial optimization must wait for all active
riders' endpoint confirmations, including at the API boundary.

Test a rider-only reroute from actual current position or an explicitly
chosen last completed stop. Preserve completed orders and other riders'
package ownership/routes. An endpoint change reroutes only that rider.
Same-building orders share navigation stops but retain distinct statuses
and underlying capacity demand. Resolve postponed reinsertion semantics.
Order statuses are exactly Pending, Postponed and Completed.

Verify the selected provider with a real directed road matrix. Test errors,
unreachable pairs, limits and timeouts. Never label straight-line or mocked
distances as real road optimization. Document two-wheeler coverage, request
cost estimates, cache/display rights and Leaflet compatibility. If live
credentials are unavailable, complete independent work and mark that gate
Blocked; do not claim Phase 0 complete. Do not enable unapproved paid services.

Prototype safe map-link resolution with manual fallback and private-network
protection. Plan secure role sessions, own-rider offline storage and an
idempotent versioned status queue. Offline rerouting requires connectivity.

Do not add fuel analytics, a postponed dashboard, a separate balanced mode
or compulsory package/dispatch confirmation. Only selected add-ons 2/4/8/9
are included. Keep real contacts, home coordinates and keys out of fixtures,
logs, Git and Notion.

Work autonomously on reversible local tasks. Ask only for genuinely blocking
inputs, spending or account access. Record assumptions and decisions. Run
meaningful checks and preserve failures/unrun cases. Produce exact commands,
dependency versions, test evidence, known limits and a concise Phase 0 report.
Stop before Phase 1 and present the report for human acceptance. Prepare the
Notion update diff after acceptance; never claim automatic synchronization.
```
