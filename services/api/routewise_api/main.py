"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import ProgrammingError

from .config import REPO_ROOT, Settings, load_settings
from .db import make_engine, make_session_factory
from .deps import utcnow
from .planning import PlanningService, recover_interrupted_runs
from .routers import admin, admin_groups, admin_planning, admin_riders, auth, rider

MAX_BODY_BYTES = 3 * 1024 * 1024  # covers the 2 MiB workbook limit plus multipart overhead
WEB_DIST = REPO_ROOT / "apps" / "web" / "dist"

# Never log request bodies or SQL; uvicorn's access log shows method, path (ids only) and status.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
log = logging.getLogger("routewise")


class BodySizeLimit:
    """Reject oversized request bodies while streaming, before multipart parsing spools them."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            return await self._reject(send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await self._reject(send)

    @staticmethod
    async def _reject(send):
        body = b'{"detail":"Request too large"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",  # location only for our own origin (rider reroute); never "*"
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


REVALIDATE = {"Cache-Control": "no-cache"}
# A service worker script needs a JavaScript type, and the manifest its own; do not rely on the platform's MIME table.
SHELL_TYPES = {".js": "text/javascript", ".webmanifest": "application/manifest+json"}


def create_app(settings: Settings | None = None, clock: Callable[[], datetime] | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="RouteWise API", docs_url=None if settings.is_production else "/api/docs",
                  redoc_url=None, openapi_url=None if settings.is_production else "/api/openapi.json")
    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = clock or utcnow
    app.state.planning = PlanningService(settings, app.state.session_factory, app.state.clock)
    try:  # runs left queued/running by a previous process are reported as interrupted, never successful
        recover_interrupted_runs(app.state.session_factory, app.state.clock())
    except ProgrammingError:
        log.warning("planning tables missing; run `alembic upgrade head`")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # customer data must not land in shared caches
        elif request.url.path.startswith("/assets/") and response.status_code in (200, 304):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # Vite content-hashes these names
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # FastAPI's default echoes the submitted input; return field locations and messages only.
        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(admin_riders.router)
    app.include_router(admin_planning.router)
    app.include_router(admin_groups.router)
    app.include_router(rider.router)

    if WEB_DIST.is_dir():  # production-style single origin: built SPA served by the API
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            # index.html, sw.js, the manifest and the icons keep fixed names: the browser must revalidate them on every use
            # (ETag), or a new build and a new service worker would never be noticed. Only /assets/* is immutable.
            candidate = (WEB_DIST / path).resolve()
            if path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
                return FileResponse(candidate, media_type=SHELL_TYPES.get(candidate.suffix), headers=REVALIDATE)
            return FileResponse(WEB_DIST / "index.html", headers=REVALIDATE)

    app.add_middleware(BodySizeLimit, limit=MAX_BODY_BYTES)
    return app


def get_app() -> FastAPI:  # uvicorn --factory routewise_api.main:get_app
    return create_app()

