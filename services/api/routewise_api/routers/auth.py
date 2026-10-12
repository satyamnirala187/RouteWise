"""Sign-in, sign-out and current-session endpoints. No self-registration (not in approved scope)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DBSession

from ..config import Settings
from ..deps import CurrentUser, check_origin, get_db, get_now, get_settings, require_user
from ..models import LoginFailure, Session, User
from ..security import new_token, token_digest, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

THROTTLE_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_USERNAME = 5
MAX_FAILURES_PER_IP = 20


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _session_view(current: CurrentUser) -> dict:
    return {
        "username": current.user.username,
        "role": current.user.role,
        "rider_name": current.rider.display_name if current.rider else None,
        "csrf_token": current.session.csrf_token,
    }


def _set_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=int(settings.session_absolute.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
) -> dict:
    check_origin(request, settings)  # login CSRF: only our own pages may post credentials
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "JSON required")
    key = body.username.strip().lower()
    ip = request.client.host if request.client else "unknown"
    since = now - THROTTLE_WINDOW
    db.execute(delete(LoginFailure).where(LoginFailure.at < since))
    by_user = db.scalar(select(func.count()).where(LoginFailure.username_key == key, LoginFailure.at >= since))
    by_ip = db.scalar(select(func.count()).where(LoginFailure.ip == ip, LoginFailure.at >= since))
    if by_user >= MAX_FAILURES_PER_USERNAME or by_ip >= MAX_FAILURES_PER_IP:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed sign-in attempts; try again later")

    user = db.scalar(select(User).where(User.username == key))
    ok, rehash = verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None or not user.active:
        db.add(LoginFailure(username_key=key, ip=ip, at=now))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    if rehash:
        user.password_hash = rehash
    db.execute(delete(LoginFailure).where(LoginFailure.username_key == key))
    token = new_token()
    db.add(Session(token_hash=token_digest(settings.secret_key, token), user_id=user.id,
                   csrf_token=new_token(), created_at=now, last_seen_at=now))
    _set_cookie(response, settings, token)
    return {"ok": True, "role": user.role}


@router.get("/session")
def current_session(current: CurrentUser = Depends(require_user)) -> dict:
    return _session_view(current)


@router.post("/logout")
def logout(
    response: Response,
    current: CurrentUser = Depends(require_user),  # requires CSRF token
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
) -> dict:
    current.session.revoked_at = now
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    return {"ok": True}
