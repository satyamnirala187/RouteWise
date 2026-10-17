"""Admin endpoints for Phase 2A: Office/Warehouse, rider profiles and per-round rider setup.

Accounts are still created and deactivated only through the CLI. There is no endpoint that
selects or confirms a destination for a rider, and no admin response carries Home/Custom
destination coordinates (see riders.py for the confirmation and locking rules)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session as DBSession

from ..config import Settings
from ..deps import CurrentUser, get_db, get_now, get_settings, require_admin
from ..locations import manual_pin
from ..models import MAX_CAPACITY, DeliveryRound, Depot, Rider, RiderEndpoint, RoundRider, User
from ..riders import (
    DEPOT_NAMES,
    admin_round_rider_view,
    bump_config,
    bump_round_input,
    depot_users,
    depot_view,
    is_confirmed,
    lock_depots_shared,
    lock_round,
    lock_round_rider,
    rider_profile_view,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

Vehicle = Literal["scooter", "bike"]
StartKind = Literal["office", "warehouse"]
Capacity = Annotated[StrictInt, Field(ge=1, le=MAX_CAPACITY)]


# ------------------------------------------------------------------ Office and Warehouse


class DepotIn(BaseModel):
    version: StrictInt | None = None  # None creates the depot; otherwise the version being edited
    label: str = Field(min_length=1, max_length=100)
    lat: float
    lng: float


@router.get("/depots")
def list_depots(db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings)) -> dict:
    depots = {d.kind: d for d in db.scalars(select(Depot)).all()}
    return {k: depot_view(depots[k], settings.service_area) if k in depots else None for k in DEPOT_NAMES}


@router.put("/depots/{kind}")
def set_depot(kind: StartKind, body: DepotIn, current: CurrentUser = Depends(require_admin),
              db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
              now: datetime = Depends(get_now)) -> dict:
    label = body.label.strip()
    if not label:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "label is required")
    loc = manual_pin(body.lat, body.lng)
    if not loc.resolved:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, loc.note)
    if not settings.service_area.contains(loc.lat, loc.lng):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"The {DEPOT_NAMES[kind]} must be inside the DU North Campus service area")
    depot = db.get(Depot, kind, with_for_update=True, populate_existing=True)
    if body.version is None:
        if depot is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"The {DEPOT_NAMES[kind]} already exists; reload and edit it")
        created = db.scalar(pg_insert(Depot).values(kind=kind, label=label, lat=loc.lat, lng=loc.lng,
                                                    updated_by=current.user.id, updated_at=now)
                            .on_conflict_do_nothing(index_elements=["kind"]).returning(Depot.kind))
        if created is None:  # another admin created it first
            raise HTTPException(status.HTTP_409_CONFLICT, f"The {DEPOT_NAMES[kind]} already exists; reload and edit it")
        depot = db.get(Depot, kind, with_for_update=True, populate_existing=True)
        moved = True
    else:
        if depot is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"The {DEPOT_NAMES[kind]} has not been set yet")
        if depot.version != body.version:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"The {DEPOT_NAMES[kind]} changed since you opened it; reload and try again")
        moved = (depot.lat, depot.lng) != (loc.lat, loc.lng)
        depot.label, depot.lat, depot.lng = label, loc.lat, loc.lng
        depot.version += 1
        depot.updated_by, depot.updated_at = current.user.id, now
    invalidated = 0
    if moved:
        # Riders whose start or destination uses this depot confirmed its old coordinates.
        # Locking order: this depot (held) → their rounds → their round-rider rows.
        round_ids = sorted({rr.round_id for rr in depot_users(db, kind)})
        for round_id in round_ids:
            lock_round(db, round_id)
        # Config writers hold this depot FOR SHARE first, so the set cannot change under our lock.
        affected = depot_users(db, kind)
        for rr in affected:
            rr = lock_round_rider(db, rr.round_id, rr.rider_id)
            invalidated += is_confirmed(rr) and rr.participating
            bump_config(db, rr, now, bump_round=False)
        for round_id in sorted({rr.round_id for rr in affected}):  # each round's planning input advances once
            bump_round_input(db, round_id)
    view = depot_view(depot, settings.service_area)
    view["confirmations_invalidated"] = int(invalidated)
    return view


# ------------------------------------------------------------------ rider profiles


class RiderPatch(BaseModel):
    version: StrictInt
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    default_vehicle: Vehicle | None = None


@router.get("/riders")
def list_riders(db: DBSession = Depends(get_db, scope="function")) -> list[dict]:
    rows = db.execute(select(Rider, User).join(User, User.id == Rider.user_id).order_by(Rider.display_name, Rider.id)).all()
    return [rider_profile_view(r, u) for r, u in rows]


@router.patch("/riders/{rider_id}")
def edit_rider(rider_id: uuid.UUID, body: RiderPatch, db: DBSession = Depends(get_db, scope="function")) -> dict:
    """Profile only (name, default vehicle for new round setups). Round setups are unchanged,
    so no rider has to confirm again because of a profile edit."""
    rider = db.get(Rider, rider_id, with_for_update=True, populate_existing=True)
    if rider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    if rider.version != body.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "This rider changed since you opened it; reload and try again")
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "display name is required")
        rider.display_name = name
    if body.default_vehicle is not None:
        rider.vehicle = body.default_vehicle
    rider.version += 1
    return rider_profile_view(rider, db.get(User, rider.user_id))


# ------------------------------------------------------------------ per-round rider setup


class RoundRiderIn(BaseModel):
    version: StrictInt | None = None  # None adds the rider to the round; otherwise the config_version being edited
    participating: bool | None = None
    vehicle: Vehicle | None = None
    capacity: Capacity | None = None
    start: StartKind | None = None


def _round_or_404(db: DBSession, round_id: uuid.UUID) -> DeliveryRound:
    rnd = lock_round(db, round_id)
    if rnd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    return rnd


def _round_rider_rows(db: DBSession, round_id: uuid.UUID, rider_id: uuid.UUID | None = None):
    q = (select(RoundRider, Rider, User, RiderEndpoint)
         .join(Rider, Rider.id == RoundRider.rider_id)
         .join(User, User.id == Rider.user_id)
         .outerjoin(RiderEndpoint, (RiderEndpoint.round_id == RoundRider.round_id)
                    & (RiderEndpoint.rider_id == RoundRider.rider_id))
         .where(RoundRider.round_id == round_id)
         .order_by(Rider.display_name, Rider.id))
    if rider_id is not None:
        q = q.where(RoundRider.rider_id == rider_id)
    return db.execute(q).all()


@router.get("/rounds/{round_id}/riders")
def list_round_riders(round_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"),
                      settings: Settings = Depends(get_settings)) -> list[dict]:
    if db.get(DeliveryRound, round_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    depots = {d.kind: d for d in db.scalars(select(Depot)).all()}
    return [admin_round_rider_view(rr, r, u, e, depots, settings.service_area)
            for rr, r, u, e in _round_rider_rows(db, round_id)]


@router.put("/rounds/{round_id}/riders/{rider_id}")
def set_round_rider(round_id: uuid.UUID, rider_id: uuid.UUID, body: RoundRiderIn,
                    db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
                    now: datetime = Depends(get_now)) -> dict:
    """Add a rider to a round (version omitted) or change their setup. Any accepted change to
    participation, vehicle, capacity or start invalidates that rider's confirmation."""
    depots = lock_depots_shared(db)
    _round_or_404(db, round_id)
    rider = db.get(Rider, rider_id)
    if rider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    user = db.get(User, rider.user_id)
    rr = lock_round_rider(db, round_id, rider_id)
    if rr is None:
        if body.version is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This rider is not part of the round yet")
        vehicle = body.vehicle or rider.vehicle
        missing = [f for f, v in (("vehicle", vehicle), ("capacity", body.capacity), ("start", body.start)) if v is None]
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Choose {', '.join(missing)} for this rider")
        participating = True if body.participating is None else body.participating
        if participating and not user.active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This rider's account is deactivated")
        rr = RoundRider(round_id=round_id, rider_id=rider_id, participating=participating, vehicle=vehicle,
                        capacity=body.capacity, start_kind=body.start, config_version=1, created_at=now, updated_at=now)
        db.add(rr)
        db.flush()
        bump_round_input(db, round_id)
    else:
        if body.version is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This rider is already part of the round; reload and edit")
        if rr.config_version != body.version:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This rider's setup changed since you opened it; reload and try again")
        if body.participating and not rr.participating and not user.active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This rider's account is deactivated")
        changes = {"participating": body.participating, "vehicle": body.vehicle, "capacity": body.capacity,
                   "start_kind": body.start}
        changed = False
        for field, value in changes.items():
            if value is not None and getattr(rr, field) != value:
                setattr(rr, field, value)
                changed = True
        if changed:
            bump_config(db, rr, now)
    db.flush()
    (row,) = _round_rider_rows(db, round_id, rider_id)
    return admin_round_rider_view(*row, depots, settings.service_area)
