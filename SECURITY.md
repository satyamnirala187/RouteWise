# Security policy

RouteWise is in development and is **not deployed**. This repository holds source code,
synthetic test data and test evidence only; it contains no real customer data and no
credentials. It is not production-ready.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** through GitHub's private vulnerability
reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Do not
open a public issue, pull request or discussion for a security problem.

Please include what is affected (file, endpoint or commit), how to reproduce it and the impact
you expect. Do not access data that is not yours, and do not test against any system you do not
own: there is no hosted RouteWise service to test.

This is a small owner-run project. Reports are read on a best-effort basis; there is no bug
bounty.

## Supported versions

Only the latest commit on `main` is maintained.

## Scope notes

- Secrets belong only in the git-ignored `.env` (see `.env.example`); none are committed.
- Tests use synthetic customers and public OpenStreetMap points. Planning tests replay
  recorded road matrices; no live map tiles or paid map services are used in CI.
- See [docs/SECURITY-REVIEW.md](docs/SECURITY-REVIEW.md) for the most recent review.
