# Security review before publication

**Date:** 19 October 2026 · **Prepared by:** Claude Code · **Repository:** https://github.com/satyamnirala187/RouteWise (made **public** on 19 October 2026, with the owner's authorization).

RouteWise is in development and is **not deployed** and **not production-ready**. Public source is not a deployment: no server, database or GitHub Pages site is exposed. This review lowers risk; it does not guarantee that no problem remains.

## 1. Scope

- **Git history:** all 16 commits on all branches, including Dependabot's branches. There are no tags. Every version of every file was scanned, not just the latest.
- **Contents:** source, tests and fixtures, the docs (including the verbatim `docs/source/` package), evidence files, 98 screenshots and commit metadata.
- **GitHub repository contents:**
  - Actions runs, logs and artifacts; repository and Actions secrets and variables; environments;
  - releases, tags, issues and pull requests; deployments, webhooks, deploy keys, collaborators, forks;
  - Pages and wiki.
- **Application security:** authentication, authorization, CSRF, input handling, production configuration, dependencies.

## 2. Tools

- **gitleaks 8.30.1:** official release binary, SHA-256 verified against the release checksums. Run as `gitleaks git --log-opts=--all --redact=100` over the full history, twice: before the final changes (10 commits) and just before publication (16 commits).
- **Targeted pattern checks** over every file version in history:
  - emails, Indian phone numbers, Delhi and Bengaluru coordinate pairs, URLs and IP addresses;
  - cloud and API key formats, Notion links and IDs, Google Maps short links;
  - an inventory of file types, and PNG text/EXIF metadata.
- **Comparison against generated test credentials:** the passwords and database URL generated for the local browser tests were compared against the staged text without printing them.
- **Dependency audits:** `npm audit` (production and dev); **pip-audit 2.10.1** (PyPA) on `services/api/requirements.lock`, `spikes/routing/requirements.lock` and `requirements-valhalla.lock`.
- **GitHub CodeQL** default setup after publication: Actions, Python and JavaScript/TypeScript.
- **Manual review** of the authentication, authorization, CSRF, configuration and upload code.

## 3. Findings

No credentials, private keys, database secrets, real customer data or private rider locations were found.

| # | Category | Where | Assessment |
|---|---|---|---|
| 1 | Generic API key (gitleaks) | `services/api/routewise_api/main.py`, first commit `fcac55e` | **False positive:** the documentation path `/api/openapi.json` (entropy 3.55). No key |
| 2 | Personal email in commit metadata | Author/committer of the 10 commits before this review | A personal Gmail address. Removing it needs a history rewrite and force-push. **Owner decision: publish as-is.** Later commits use the GitHub noreply address (repo-local git setting) |
| 3 | Phone-like numbers | `services/api/tests/test_import.py`, `services/api/scripts/e2e_setup.py` | Synthetic "Test Customer" contacts, but formatted like real Indian mobile numbers. Not known to belong to anyone. Other matches are OpenStreetMap node IDs in public fixtures and a commit-hash fragment |
| 4 | Coordinates | tests, UI format hints, spike scripts | Public OSM points (DU North Campus; Bengaluru landmarks in historical Phase 0 tests), a deliberately out-of-area point and bounding boxes. No private Home/Custom location; "Home" in screenshots is a public station used as a synthetic role |
| 5 | Notion link | `docs/source/START-HERE.md` (verbatim package, not edited) | Link to the owner's Notion workspace page. Access depends on that page's Notion sharing settings, which this review did not change or check |
| 6 | Emails in text | `docs/phase0/STADIA-SUITABILITY.md`; `services/api/tests/test_locations.py` | A public vendor contact; synthetic URLs with fake user-info used in link-parsing tests |
| 7 | Provider evidence | `spikes/routing/evidence/google_routes_check.json`, `stadia_matrix_check.json` | Status stubs ("not run" with a reason): no Google or Stadia response content. Other captures come from the local Valhalla and the public OSRM demo (OpenStreetMap data, attributed) |
| 8 | Screenshots | 98 PNGs under `docs/phase1–3/screenshots` | Test screenshots of synthetic data, inspected when they were taken; no PNG text or EXIF metadata |
| 9 | CI logs (found and fixed in this review) | First CI runs | The random per-run session key appeared in step environment listings. It protected nothing persistent, but the workflow now masks it (`::add-mask::`), and the 5 runs whose logs contained it were **deleted before publication**. The remaining run shows no unmasked value |
| 10 | GitHub contents | Repository | Before publication: no releases, tags, issues, pull requests, Actions secrets or variables, environments, deployments, webhooks, deploy keys or Pages; wiki off; one collaborator (owner). Dependabot opened 3 version-update pull requests (#1–#3) while still private; they contain only dependency bumps and are left for the owner |

**Application review** (no material problem found for a non-deployed development app):
- **Authorization:** every admin and rider router requires its role at router level; rider data is filtered by ownership in the query (another rider's order or round is a 404).
- **CSRF:** mutations require the session CSRF token plus an allowed Origin/Referer; login checks Origin.
- **Sessions:** server-side and revocable; cookies are HttpOnly and SameSite=Lax, Secure with the `__Host-` prefix in production.
- **Passwords:** Argon2id; login throttling per username and per IP.
- **Startup checks:** refuses to start with a session secret shorter than 32 characters, or in production without Secure cookies. API docs are off in production.
- **Headers:** a restrictive CSP, `nosniff`, `DENY` framing, `same-origin` referrer, `no-store` on API responses, HSTS in production.
- **Inputs:** request bodies are size-limited (413); Excel import has size, row and compression-ratio limits and refuses formulas.
- **Network fetches:** short links go only through the SSRF-guarded fetcher (validated public IP, hostname-verified TLS, headers only).
- **Data:** no customer fields in logs (tested).

**Notes for any future deployment** (not blockers today):
- Login throttling uses the client IP and must be configured correctly behind a proxy.
- One API process per database.
- No backups, HTTPS or monitoring yet.
- No retention purge (D10).

**Dependencies:**
- `npm audit`: 0 vulnerabilities.
- pip-audit: no known vulnerabilities in the three Python lock files.
- CodeQL: 0 open alerts.
- Secret scanning and Dependabot: 0 open alerts at the time of writing.

## 4. Fixes made in this review

- CI masks its per-run session key; the 5 earlier runs whose logs showed it were deleted.
- The CI API job builds the web app first, so the static-file and path-traversal security test runs in CI. It had been skipped.
- New commits use the GitHub noreply email (repo-local setting).

## 5. Repository protections (verified through the GitHub API after publication)

| Protection | Status |
|---|---|
| Secret scanning | **Enabled** |
| Secret scanning push protection | **Enabled** |
| Dependabot alerts | **Enabled** |
| Dependabot security updates | **Enabled** |
| Dependabot version updates (`.github/dependabot.yml`: npm, pip, GitHub Actions; weekly) | **Configured** (first PRs #1–#3 opened) |
| Dependency graph | **Active:** npm (183 packages), GitHub Actions (3), PyPI (21 top-level packages from `requirements.in`). The full Python lock files are not parsed by GitHub, so CI also runs pip-audit on `services/api/requirements.lock` |
| Code scanning (CodeQL default setup: Actions, Python, JavaScript/TypeScript) | **Enabled**; first analysis succeeded, 0 open alerts |
| Ruleset "Protect main" (default branch): block deletion and force-push (`non_fast_forward`) | **Active**, no bypass actors |
| Private vulnerability reporting | **Enabled**; see [SECURITY.md](../SECURITY.md) |
| CI (`.github/workflows/ci.yml`) | **Passing.** Details below |
| Secret scanning for non-provider patterns, validity checks | **Not enabled:** paid GitHub Advanced Security features; outside the ₹0 budget |
| Required pull-request reviews and status checks | **Not configured:** single-owner repository with direct pushes; requiring them would block the owner's normal workflow. Can be added later |

CI details:
- **Permissions and isolation:** `contents: read`; actions pinned to commit SHAs; `persist-credentials: false`; `pull_request` only (no `pull_request_target`); no repository secrets.
- **Jobs:**
  - web: typecheck, 17 unit tests, build, npm audit;
  - API: 355 passed and 1 skipped (opt-in live test), on a throwaway PostgreSQL 18 container with **recorded** road matrices, plus pip-audit;
  - routing regression: 264 passed, 5 skipped.
- **Not needed:** no live map tiles and no real credentials.

No license was added; that is left to the owner. GitHub Pages is not configured.

## 6. Limitations

- **Gaps:** scanners and patterns find known shapes, so a secret or personal detail in an unusual format could be missed. The Notion page's sharing settings and the meaning of the synthetic phone-like numbers were not verified outside this repository.
- **Commit email:** the personal address in the first 10 commits is now public by the owner's decision, and cannot be withdrawn without rewriting published history.
- **Browser tests:** not run in CI (they need a local PostgreSQL cluster, the browser test server and screenshots); they run locally.
- **Not an audit:** this was not a penetration test or a third-party audit. The application has never been deployed and is not production-ready. Phase 3 is not accepted: real-phone Call/Google Maps checks remain unperformed.
