"""Browser-test API factory (step 2C). Used only by apps/web/playwright.config.ts:

    uvicorn --factory scripts.e2e_app:get_app --app-dir services/api

It builds the normal application and then, unless ROUTEWISE_E2E_LIVE=1, injects the recorded
real local-Valhalla DU matrices through the same test-only seam the API tests use
(`app.state.planning.provider_override`). This module is outside the `routewise_api` package
and is not selectable through configuration; it refuses to run in production.

Hold seam: while the file `<state dir>/hold-solve` exists, matrix computation waits (at most
90 s), so a browser test can change input while a run is in progress. Removing the file lets
the run continue. Nothing else is changed: prechecks, stale detection and commit are real.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from routewise_api.config import REPO_ROOT
from routewise_api.main import create_app

HOLD = REPO_ROOT / ".local" / "e2e" / "hold-solve"
MAX_HOLD_S = 90


class Held:
    """Wraps a matrix provider; waits while the hold file exists."""

    def __init__(self, inner, hold: Path = HOLD):
        self.inner, self.hold = inner, hold
        self.name = getattr(inner, "name", "provider")

    def compute(self, origins, destinations, profile):
        end = time.monotonic() + MAX_HOLD_S
        while self.hold.exists() and time.monotonic() < end:
            time.sleep(0.1)
        return self.inner.compute(origins, destinations, profile)


def get_app():
    app = create_app()
    if app.state.settings.is_production:
        raise RuntimeError("scripts.e2e_app is for local browser tests only")
    if os.environ.get("ROUTEWISE_E2E_LIVE") == "1":
        # Real local Valhalla tiles; the hold seam still applies so live runs use the same flow.
        app.state.planning.provider_override = Held(app.state.planning.provider())
    else:
        from tests.recorded_matrix import RecordedDUProvider

        app.state.planning.provider_override = Held(RecordedDUProvider())
    return app
