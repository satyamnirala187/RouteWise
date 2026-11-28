"""Browser-test API factory for the offline app-shell specs (step 5A-1). Used only by apps/web/playwright.fastapi.config.ts
and by the specs' own killable servers (apps/web/e2e/shell-server.ts):

    E2E_WEB_DIST=<a built web app> uvicorn --factory scripts.e2e_shell_app:get_app --app-dir services/api

It is the same app as scripts.e2e_app (recorded matrices, refuses production), but it serves the web build named by
E2E_WEB_DIST instead of apps/web/dist. A test can therefore serve several builds, and never rebuilds or touches the
build that the owner's phone server serves.
"""

from __future__ import annotations

import os
from pathlib import Path

import routewise_api.main as main
from scripts.e2e_app import get_app as e2e_app


def get_app():
    main.WEB_DIST = Path(os.environ["E2E_WEB_DIST"]).resolve()  # read by create_app and the SPA route at call time
    return e2e_app()
