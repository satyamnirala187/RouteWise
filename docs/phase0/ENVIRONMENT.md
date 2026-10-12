# Phase 0 environment record

Recorded 12 October 2026 (Asia/Kolkata), on the development Mac.

## Machine and tools

| Item | Observed |
|---|---|
| OS | macOS 27.0.1 (build 26A434), arm64 |
| Python used for the spike | 3.14.3, python.org framework build (`/Library/Frameworks/Python.framework/Versions/3.14`) |
| Apple system Python | 3.9.6 at `/usr/bin/python3`; not used and not modified |
| Node / npm | 24.18.1 (nvm) / 11.16.0 (not used in Phase 0) |
| Git | 2.54.0 (Apple Git-157) |
| Claude Code CLI | 2.1.296 |
| Homebrew, uv, pyenv | Not installed |
| PostgreSQL, Docker | Not installed (only needed from Phase 1) |

## Python 3.14 compatibility

`pip index versions` (which filters by interpreter) showed `ortools 9.15.6755` as the only release with a cp314 macOS arm64 wheel. OR-Tools solved a toy routing problem under 3.14.3 before the spike was built. **Python 3.12 is not needed.** No second runtime was installed, and system Python was not touched.

Known warnings under 3.14, harmless for now:
- OR-Tools SWIG bindings emit `DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute`.
- `fastapi.testclient` emits `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2`. Recheck this when the Phase 1 API test stack is pinned.

## Isolated environment

`spikes/routing/.venv` is a project-local venv. It is git-ignored and is recreated from the lock file.

Direct dependencies (`spikes/routing/requirements.in`) are pinned exactly, and the full transitive set is frozen in `spikes/routing/requirements.lock`:

| Package | Version | Purpose in Phase 0 |
|---|---|---|
| ortools | 9.15.6755 | Vehicle routing solver |
| fastapi | 0.143.0 | Spike API boundary for the confirmation gate |
| httpx | 0.28.1 | Provider adapters (mockable transport) |
| pandas | 3.0.6 | Import-library compatibility check only |
| openpyxl | 3.1.5 | Import-library compatibility check only |
| pytest | 9.1.1 | Tests |
| numpy / protobuf / pydantic / starlette | 2.5.4 / 6.33.6 / 2.14.1 / 1.7.0 | Transitive |

## Reproduce from a clean checkout

```bash
cd spikes/routing
./run_phase0.sh          # creates .venv from requirements.lock, runs tests, scenario, cost projection, google-check
```

Or step by step:

```bash
cd spikes/routing
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest -q                                   # offline; uses the recorded real matrix
.venv/bin/python -m routewise_spike run-scenario --matrix recorded
.venv/bin/python -m routewise_spike cost-projection
.venv/bin/python -m routewise_spike benchmark                   # ~40 s; synthetic matrix, timing only
.venv/bin/python -m routewise_spike google-check                # BLOCKED without GOOGLE_MAPS_API_KEY
ROUTEWISE_LIVE_TESTS=1 .venv/bin/python -m pytest -q -m live    # opt-in network tests
.venv/bin/python -m routewise_spike capture-osrm                # re-captures the public OSRM matrix (network)
```

A clean-checkout run was verified by copying only the files Git would track into a scratch directory and running `run_phase0.sh` there with a fresh venv. The result is in [PHASE0-REPORT.md](PHASE0-REPORT.md#commands-run-and-actual-results).
