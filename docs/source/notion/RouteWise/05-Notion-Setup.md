# Notion import and tracker setup

[Home](../RouteWise.md)

**Current delivery:** Live Notion workspace created through the signed-in browser on 12 October 2026. [Open home](https://app.notion.com/p/RouteWise-Development-3f792c584dbd81439393e3e4ff49fb67). Six phases, 38 tasks, 28 acceptance cases and 11 decisions imported. Phase and task status/date/priority properties configured; live milestones and task board added. Remaining instructions are reusable reference.

## Import once

1. In Notion desktop/web, choose **Settings → Import → ZIP**, or `/zip` → **Convert Zip to pages**. Upload `RouteWise-Notion-Import.zip`.
2. Locate **RouteWise | Development**, keep it private in the intended workspace and add it to Favorites. Put the documentation and four databases beneath this home page if the importer places them as siblings.
3. Open the home-page index. Check every imported page/database link. If a relative link did not convert, replace it using `@` and the imported page name or **Copy link**. No live Notion links exist in the local package.
4. Configure the four databases below. CSV import carries rows/columns, not finished views, relations or formulas.
5. Add linked database views to the home page, then remove its static phase snapshot. Use **Phases** and **Tasks** as the editable status sources.

If ZIP import fails, inspect for partial imports first to avoid duplicates. Import the `.md` files with **Text & Markdown**, then each `.csv` with **CSV**, selecting the same private parent. Import adds records; do not repeatedly import to update existing rows. [Official Notion import guide](https://www.notion.com/help/import-data-into-notion).

## Phases database

| Property | Notion type |
|---|---|
| Phase | Title |
| ID | Text |
| Status | Status: Not started, In progress, In review, Blocked, Done |
| Owner | Text initially; replace with Person once actual members are selected |
| Priority | Select: High, Medium, Low |
| Depends on | Text of stable IDs initially; optional self-relation after import |
| Start date / Due date / Completion date | Date |
| Outcome / Completion criteria | Text |
| GitHub / Demo / Decision link / QA evidence | URL when populated with actual destinations |
| Human approval | Text: approver, date and approval reference |

## Tasks database

| Property | Notion type |
|---|---|
| Task | Title |
| ID | Text, stable and unique |
| Phase | Select: Setup, P0, P1, P2, P3, P4, P5; optionally replace with relation |
| Owner | Text, initially Unassigned; do not invent people |
| Status | Status: Not started, In progress, In review, Blocked, Done |
| Priority | Select: High, Medium, Low |
| Dependencies | Text IDs initially; optional self-relation |
| Start date / Due date / Completion date | Date |
| Acceptance criteria / Requirements / QA evidence / Notes | Text |
| GitHub / Demo / Decision link | URL when actual links exist |

Imported date strings use MM/DD/YYYY, as the importer documents. Set display to a consistent day-month format after import if preferred. Planned dates are deliberately empty. Setup document completion dates are 12 October 2026 only where work actually exists.

## Acceptance cases database

**Case** (Title), **ID** (Text), **Phase** (Select), **Requirements**, **Scenario**, **Expected result** (Text), **Result** (Select: Not run, Passed, Failed, Blocked), **Evidence** (URL/Text), **Tester** (Person when known), **Run date** (Date), **Commit** (Text).

All product cases start **Not run**. Run evidence belongs to an exact code revision and environment. A written scenario is not a passed test.

## Decisions database

**Decision** (Title), **ID** (Text), **State** (Select: Confirmed requirement, Selected for kickoff, Proposed, Pending), **Choice**, **Rationale**, **Evidence**, **Owner**, **Review gate** (Text), **Decision date** (Date).

Only explicit product requirements are confirmed. A library's documented support is evidence, not proof of our implementation. Keep alternatives in each decision page body when deciding.

## Useful views

| View | Source and setup |
|---|---|
| Current phase | Phases, Status is not Done; sort ID ascending; show phase, status, owner, next gate |
| Milestones | Phases, table with dates, outcome, QA and human approval |
| This phase | Tasks, Phase = P0 initially, Status is not Done; sort priority then ID |
| Delivery board | Tasks board grouped by Status; hide long evidence columns |
| Blockers | Tasks, Status = Blocked; show dependencies, owner and notes |
| Completed work | Tasks, Status = Done; show completion date and evidence |
| QA to run | Acceptance cases, Result is Not run or Failed or Blocked |
| Decisions to make | Decisions, State = Proposed or Pending |

Do not mark phases Done from a formula alone. Human acceptance remains an explicit field. If relations and a rollup are added later, use them for task counts and supporting progress only.

## Page style

Use the home page title, a single current-status callout, the four requested opening sections, compact phase/task views and a short project library. Keep detailed technical material in subpages. Use default Notion typography and consistent headings; put long QA evidence inside task pages. Avoid a homepage full of placeholder charts.

## Setup verification

- Confirm six phase rows are present, all Not started.
- Confirm all task and case IDs are unique; only local documentation tasks are Done.
- Open every library link and the four database links.
- Edit one task owner/status, then restore it; confirm the linked view reflects the change.
- Verify blank dates are blank and completion dates were not invented by import.
- Check private sharing, no credentials/customer data, and correct workspace.
- Copy the final home URL into Project links and the ChatGPT seed; record import completion only after these checks.
