# Mac development setup

**Selected workflow:** Cursor with Claude Code in its integrated terminal.

## Verified locally on 12 October 2026

| Tool | Observation |
|---|---|
| Cursor | Running application observed |
| macOS | 27.0.1 |
| Node | 24.18.1 |
| Python | 3.14.3 |
| Git | 2.54.0 |
| Claude Code CLI | 2.1.296 |

Claude account entitlement/login, extension installation, PostgreSQL and dependency compatibility have not been verified. No tools were installed or system settings changed.

## Local checklist

1. Create a dedicated `RouteWise-Development` folder outside the Project_Ideas mirror. Copy this package there. In Cursor, use **File → Open Folder** to open it. Do not build under synced `sources/`.
2. Open Cursor's integrated terminal. Run `claude --version` and `claude doctor`. Run `claude` and complete your own login if needed. [Official setup](https://code.claude.com/docs/en/setup).
3. Optionally install Anthropic's official Claude Code extension from Cursor's Extensions view. The terminal CLI is sufficient for the kickoff. [Official IDE guide](https://code.claude.com/docs/en/vs-code).
4. Initialize a dedicated Git repository in that folder. Add `.env`, `.venv`, customer uploads, database dumps and private fixtures to `.gitignore`. Create `.env.example` with variable names only.
5. Have Claude Code check package support and create an isolated Python environment. Python 3.12 is a candidate if the solver/import packages do not support the installed 3.14 runtime. Do not replace system Python.
6. Confirm the existing Node version supports the chosen frontend tools. Pin compatible versions in package/lock files when the app is scaffolded in Phase 1.
7. Prepare public/synthetic Phase 0 locations. Choose a provider only after coverage, matrix mode, pricing and map/cache compatibility checks. Supply credentials through local environment variables, never the prompt or Notion.
8. Decide local PostgreSQL setup during foundation work. Keep database port and credentials private; record migration commands and backup approach.
9. Paste the prompt in [KICKOFF.md](KICKOFF.md). Start with Phase 0 only.

## Proposed repository shape

```text
RouteWise-Development/
  CLAUDE.md
  docs/
  apps/web/           # Phase 1
  services/api/       # Phase 1
  spikes/routing/    # Phase 0
  tests/fixtures/    # synthetic/public data
  .env.example
  .gitignore
```

GitHub repository creation and deployment are planned. Do not insert fabricated repository/demo links. Keep the official Notion update protocol human-approved after tested phases.
