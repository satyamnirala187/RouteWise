"""Settings from environment variables (loaded from the git-ignored repo-root .env in development)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE loader; existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class ServiceArea:
    """Bounding box of the local routing graph (Phase 0 buffered DU North Campus extract)."""

    south: float = 28.55
    west: float = 77.06
    north: float = 28.83
    east: float = 77.36

    def contains(self, lat: float, lng: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lng <= self.east


@dataclass(frozen=True)
class PlanningLimits:
    """Local planning bounds (step 2B). Values come from the local DU measurements recorded in
    docs/phase2/STEP-2B-REPORT.md; they are conservative application limits, not owner decisions."""

    max_pending_orders: int = 80       # Pending orders planned in one run (measured up to 120; see the 2B report)
    max_riders: int = 8                # participating riders in one run
    max_locations: int = 100           # distinct matrix points (orders, starts, fixed destinations)
    solve_seconds: int = 30            # OR-Tools safety limit per strategy, as in the accepted spike (≤ 3 strategies)
    workers: int = 1                   # planning threads per API process
    queue_size: int = 4                # queued runs per API process beyond the running ones
    stale_after_s: int = 900           # a queued/running run older than this is reported as interrupted


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    secret_key: str
    cookie_secure: bool
    allowed_origins: tuple[str, ...]
    resolve_short_links: bool
    session_idle: timedelta = timedelta(hours=12)
    session_absolute: timedelta = timedelta(days=7)
    link_budget_s: float = 10.0          # one location edit: DNS + connects + reads + redirects
    import_link_budget_s: float = 30.0   # all short links in one import, in total
    max_concurrent_imports: int = 2      # upload parsing/link checks run on bounded worker threads
    service_area: ServiceArea = field(default_factory=ServiceArea)
    valhalla_tiles: Path = REPO_ROOT / "spikes" / "valhalla" / "data" / "valhalla_tiles"  # git-ignored, built locally
    planning: PlanningLimits = field(default_factory=PlanningLimits)

    @property
    def cookie_name(self) -> str:
        # __Host- prefix: browser enforces Secure, Path=/ and no Domain attribute.
        return "__Host-rw_session" if self.cookie_secure else "rw_session"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def load_settings(database_url: str | None = None) -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    env = os.environ.get("ROUTEWISE_ENV", "development")
    secure_default = "true" if env == "production" else "false"
    settings = Settings(
        env=env,
        database_url=database_url or os.environ.get("DATABASE_URL", ""),
        secret_key=os.environ.get("ROUTEWISE_SECRET_KEY", ""),
        cookie_secure=os.environ.get("ROUTEWISE_COOKIE_SECURE", secure_default).lower() == "true",
        allowed_origins=tuple(
            o.strip()
            for o in os.environ.get(
                "ROUTEWISE_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000"
            ).split(",")
            if o.strip()
        ),
        resolve_short_links=os.environ.get("ROUTEWISE_RESOLVE_SHORT_LINKS", "true").lower() == "true",
        valhalla_tiles=Path(os.environ.get("ROUTEWISE_VALHALLA_TILES")
                            or REPO_ROOT / "spikes" / "valhalla" / "data" / "valhalla_tiles"),
    )
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set (run scripts/dev-db.sh init)")
    if len(settings.secret_key) < 32:
        raise RuntimeError("ROUTEWISE_SECRET_KEY must be at least 32 characters")
    if settings.is_production and not settings.cookie_secure:
        raise RuntimeError("Refusing to run in production without Secure cookies")
    return settings
