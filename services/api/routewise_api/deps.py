"""Request dependencies: DB session, clock, authenticated user, role checks and CSRF.

Every protected endpoint declares `Depends(require_admin)` / `Depends(require_rider)` /
`Depends(require_user)`. Mutating methods additionally pass the CSRF check inside
`require_user`. Frontend hiding is never relied on.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .config import Settings
from .models import Rider, Session, User
from .security import constant_time_equal, token_digest

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=60)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_now(request: Request) -> datetime:
    return request.app.state.clock()


def get_db(request: Request) -> Iterator[DBSession]:
    """Always used with scope="function": the commit completes before the response is sent,
    so a client never sees success for a transaction that later fails to commit."""
    db = request.app.state.session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@dataclass
class CurrentUser:
    user: User
    session: Session
    rider: Rider | None

    @property
    def role(self) -> str:
        return self.user.role


def check_origin(request: Request, settings: Settings) -> None:
    """Reject cross-site state changes: Origin (or Referer) must be an allowed origin."""
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        if referer:
            parts = referer.split("/", 3)
            origin = "/".join(parts[:3]) if len(parts) >= 3 else None
    if origin is not None and origin not in settings.allowed_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin request rejected")


def session_expired(sess: Session, now: datetime, settings: Settings) -> bool:
    return (
        sess.revoked_at is not None
        or now - sess.last_seen_at > settings.session_idle
        or now - sess.created_at > settings.session_absolute
    )


def require_user(
    request: Request,
    db: DBSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
) -> CurrentUser:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    sess = db.get(Session, token_digest(settings.secret_key, token))
    if sess is None or session_expired(sess, now, settings):
        if sess is not None and sess.revoked_at is None:
            sess.revoked_at = now  # expire server-side for good
            db.commit()  # get_db rolls back on exceptions; persist the revocation first
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired; sign in again")
    user = db.get(User, sess.user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    if request.method in MUTATING:
        check_origin(request, settings)
        if not constant_time_equal(request.headers.get("x-csrf-token"), sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token")
    if now - sess.last_seen_at > LAST_SEEN_WRITE_INTERVAL:
        sess.last_seen_at = now
    rider = db.scalar(select(Rider).where(Rider.user_id == user.id)) if user.role == "rider" else None
    return CurrentUser(user=user, session=sess, rider=rider)


def require_admin(current: CurrentUser = Depends(require_user)) -> CurrentUser:
    if current.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return current


def require_rider(current: CurrentUser = Depends(require_user)) -> CurrentUser:
    if current.role != "rider" or current.rider is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Rider only")
    return current


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
