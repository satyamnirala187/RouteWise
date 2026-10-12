# RouteWise | Development

**Development handoff · 12 October 2026 · Asia/Kolkata**

RouteWise will turn an Excel delivery list into practical road-based routes for multiple riders, with clear customer details and simple delivery updates.

## Current status

[Open the live RouteWise Notion workspace](https://app.notion.com/p/RouteWise-Development-3f792c584dbd81439393e3e4ff49fb67). Documentation, six phases, 38 tasks, 28 acceptance cases and 11 decisions are now imported. The home has a live milestones table and task board. Development has not started. The separate ChatGPT Project remains to be created; instructions below are ready.

## Open the project documentation

- [RouteWise home](notion/RouteWise.md) — vision, workflow, technology choices and phase status.
- [Product requirements](notion/RouteWise/01-Product.md)
- [How it works](notion/RouteWise/02-Working-Flow.md)
- [Architecture and technology decisions](notion/RouteWise/03-Architecture.md)
- [Phases and completion gates](notion/RouteWise/04-Roadmap.md)
- [Notion import and tracker setup](notion/RouteWise/05-Notion-Setup.md)
- [Testing and Phase 0 acceptance](notion/RouteWise/06-Acceptance.md)
- [Privacy and security](notion/RouteWise/07-Privacy.md)
- [Decision log](notion/RouteWise/08-Decisions.md)
- [Change log and update protocol](notion/RouteWise/09-Updates.md)
- [Pilot measurement plan](notion/RouteWise/10-Pilot.md)
- [Mac and Cursor setup](development/MAC-SETUP.md)
- [Claude Code kickoff](development/KICKOFF.md)

## Finish the two account steps

### 1. Create the separate ChatGPT Project

In ChatGPT, open **Projects → New project**, enter **RouteWise | Development**, and create it. Do not rename Project_Ideas or DataPilot. If the creation dialog offers project-only memory, choose it for separation. Open the new project's menu/settings → **Project instructions**, and paste [PROJECT-INSTRUCTIONS.md](chatgpt/PROJECT-INSTRUCTIONS.md). Add [PROJECT-SEED.md](chatgpt/PROJECT-SEED.md) and the product/architecture/roadmap/acceptance documents as project sources. Start its first chat with [FIRST-CHAT.md](chatgpt/FIRST-CHAT.md).

The exact entry-point label can differ across ChatGPT surfaces. The required action is **create a new ChatGPT Project**, not a sidebar section, local folder, or chat inside Project_Ideas. Official context: [Projects and chats](https://learn.chatgpt.com/docs/projects).

### 2. Notion workspace — completed

[Open RouteWise | Development](https://app.notion.com/p/RouteWise-Development-3f792c584dbd81439393e3e4ff49fb67). Use the existing databases for future updates, not repeated imports.

## First development action

Use **Cursor on Mac + Claude Code in Cursor's integrated terminal**. Move/copy this package into a dedicated development folder outside the Project_Ideas mirror when starting development. Follow the local setup checklist and give Claude Code the kickoff prompt. Start with **Phase 0**, whose real API results and test evidence remain outstanding.

Only the documentation is complete. All six implementation phases remain **Not started**. Dates and real account links are blank until known; proposed choices are labeled as such.
