"""Rider endpoints: a rider sees only orders assigned to them, and only their own setup and
destination for rounds they participate in. Ownership is checked in the query itself, so
another rider's order or round is indistinguishable from a missing one (404)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from ..config import Settings
from ..deps import CurrentUser, get_db, get_now, get_settings, require_rider
from ..locations import manual_pin
from ..models import Assignment, DeliveryRound, Depot, Order, RiderEndpoint, RoundRider
from ..riders import (
    PRIVATE_KINDS,
    bump_config,
    bump_round_input,
    configuration_issues,
    confirmation_state,
    lock_depots_shared,
    lock_round,
    lock_round_rider,
    rider_config_view,
)

router = APIRouter(prefix="/api/rider", tags=["rider"], dependencies=[Depends(require_rider)])


def _rider_view(o: Order) -> dict:
    # Minimal fields for delivery; no admin-only data (source rows, links, notes).
    return {
        "id": str(o.id),
        "order_code": o.order_code,
        "customer_name": o.customer_name,
        "product": o.product,
        "contact": o.contact,
        "instructions": o.instructions,
        "lat": o.lat,
        "lng": o.lng,
        "status": o.status,
    }


def _own_orders(current: CurrentUser):
    return select(Order).join(Assignment, Assignment.order_id == Order.id).where(Assignment.rider_id == current.rider.id)


@router.get("/orders")
def my_orders(current: CurrentUser = Depends(require_rider), db: DBSession = Depends(get_db, scope="function")) -> list[dict]:
    return [_rider_view(o) for o in db.scalars(_own_orders(current).order_by(Order.order_code)).all()]


@router.get("/orders/{order_id}")
def my_order(order_id: uuid.UUID, current: CurrentUser = Depends(require_rider), db: DBSession = Depends(get_db, scope="function")) -> dict:
    order = db.scalar(_own_orders(current).where(Order.id == order_id))
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return _rider_view(order)


# ------------------------------------------------------------------ own round setup and destination

NOT_FOUND = "Round not found"


class DestinationIn(BaseModel):
    kind: Literal["office", "warehouse", "home", "last_stop", "custom"]
    lat: float | None = None  # Home and Custom only
    lng: float | None = None


class ConfirmIn(BaseModel):
    config_version: StrictInt  # the version the rider was shown


def _locked_own(db: DBSession, current: CurrentUser, round_id: uuid.UUID) -> tuple[DeliveryRound, RoundRider]:
    """Lock in the documented order (depots were locked by the caller): round, then own row.
    A round the rider does not take part in is a 404, exactly like a missing one."""
    rnd = lock_round(db, round_id)
    rr = lock_round_rider(db, round_id, current.rider.id) if rnd is not None else None
    if rr is None or not rr.participating:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return rnd, rr


def _own_view(db: DBSession, rnd: DeliveryRound, rr: RoundRider, depots: dict, settings: Settings) -> dict:
    endpoint = db.get(RiderEndpoint, (rr.round_id, rr.rider_id), populate_existing=True)
    return rider_config_view(rnd, rr, endpoint, depots, settings.service_area)


@router.get("/rounds")
def my_rounds(current: CurrentUser = Depends(require_rider), db: DBSession = Depends(get_db, scope="function")) -> list[dict]:
    rows = db.execute(
        select(DeliveryRound, RoundRider, RiderEndpoint.kind)
        .join(RoundRider, RoundRider.round_id == DeliveryRound.id)
        .outerjoin(RiderEndpoint, (RiderEndpoint.round_id == RoundRider.round_id)
                   & (RiderEndpoint.rider_id == RoundRider.rider_id))
        .where(RoundRider.rider_id == current.rider.id, RoundRider.participating.is_(True))
        .order_by(DeliveryRound.created_at.desc())
    ).all()
    return [{"round_id": str(rnd.id), "round_name": rnd.name, "config_version": rr.config_version,
             "destination_kind": kind, "confirmation": confirmation_state(rr)} for rnd, rr, kind in rows]


@router.get("/rounds/{round_id}")
def my_round_setup(round_id: uuid.UUID, current: CurrentUser = Depends(require_rider),
                   db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings)) -> dict:
    rnd = db.get(DeliveryRound, round_id)
    rr = db.get(RoundRider, (round_id, current.rider.id)) if rnd is not None else None
    if rr is None or not rr.participating:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    depots = {d.kind: d for d in db.scalars(select(Depot)).all()}
    return _own_view(db, rnd, rr, depots, settings)


@router.put("/rounds/{round_id}/destination")
def choose_destination(round_id: uuid.UUID, body: DestinationIn, current: CurrentUser = Depends(require_rider),
                       db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
                       now: datetime = Depends(get_now)) -> dict:
    """Select (not confirm) a destination. A real change invalidates the rider's confirmation."""
    if body.kind in PRIVATE_KINDS:
        if body.lat is None or body.lng is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Home and Custom need a location (lat and lng)")
        loc = manual_pin(body.lat, body.lng)
        if not loc.resolved:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, loc.note)
        if not settings.service_area.contains(loc.lat, loc.lng):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "This location is outside the DU North Campus service area")
        lat, lng, source = loc.lat, loc.lng, loc.source
    else:
        if body.lat is not None or body.lng is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "Only Home and Custom take a location; Office, Warehouse and Last stop do not")
        lat = lng = source = None
    depots = lock_depots_shared(db)
    rnd, rr = _locked_own(db, current, round_id)
    endpoint = db.get(RiderEndpoint, (round_id, rr.rider_id), with_for_update=True, populate_existing=True)
    if endpoint is None:
        db.add(RiderEndpoint(round_id=round_id, rider_id=rr.rider_id, kind=body.kind, lat=lat, lng=lng,
                             location_source=source, updated_at=now))
        bump_config(db, rr, now)
    elif (endpoint.kind, endpoint.lat, endpoint.lng) != (body.kind, lat, lng):
        endpoint.kind, endpoint.lat, endpoint.lng, endpoint.location_source = body.kind, lat, lng, source
        endpoint.updated_at = now
        bump_config(db, rr, now)
    db.flush()
    return _own_view(db, rnd, rr, depots, settings)


@router.post("/rounds/{round_id}/confirm")
def confirm_setup(round_id: uuid.UUID, body: ConfirmIn, current: CurrentUser = Depends(require_rider),
                  db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
                  now: datetime = Depends(get_now)) -> dict:
    """Confirm exactly the setup version the rider was shown. Runs under the depot, round and
    round-rider locks, so a concurrent change either lands first (and this returns 409) or
    lands after (and invalidates this confirmation by raising config_version)."""
    depots = lock_depots_shared(db)
    rnd, rr = _locked_own(db, current, round_id)
    if body.config_version != rr.config_version:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "configuration_changed",
            "message": "Your setup for this round changed since you viewed it (start, vehicle, capacity, "
                       "destination or a depot location). Review the current setup and confirm again.",
            "current_version": rr.config_version,
        })
    endpoint = db.get(RiderEndpoint, (round_id, rr.rider_id), populate_existing=True)
    issues = configuration_issues(rr, endpoint, depots, True, settings.service_area)
    if issues:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {
            "code": "configuration_incomplete",
            "message": "This setup cannot be confirmed yet.",
            "issues": issues,
        })
    if rr.confirmed_version != rr.config_version:  # confirming the same version twice changes nothing
        rr.confirmed_version, rr.confirmed_at = rr.config_version, now
        bump_round_input(db, round_id)
    return _own_view(db, rnd, rr, depots, settings)
