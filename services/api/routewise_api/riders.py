"""Phase 2A: Office/Warehouse, per-round rider configuration, rider-chosen destinations, the
confirmation gate and planning readiness. No optimizer is called from here.

Confirmation rule. A rider confirms one exact `config_version` of their round setup. That
version increases (and the round's `input_version` with it) whenever an accepted change alters
something the rider confirmed:
  - participation turned on again, or off;
  - vehicle, capacity or start;
  - destination kind or Home/Custom coordinates;
  - the coordinates of the depot their start uses, or of the depot chosen as destination.
A write that changes nothing bumps nothing. Customer text edits, depot labels and rider profile
names never touch a rider's configuration. A confirmation is current only while
confirmed_version == config_version, so any of the changes above invalidates it by itself.

Locking order, used by every configuration write and every confirmation: both depot rows
(FOR SHARE, or FOR UPDATE by a depot edit) → the round row → the round-rider row. A depot
edit, an admin edit and a rider confirmation can therefore never interleave, and a confirmation
always compares against the version that will be committed.

Privacy (R24): Home/Custom coordinates are returned only to the rider who chose them. Admin
views and readiness reasons name riders and kinds, never destination coordinates.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DBSession

from .config import ServiceArea
from .models import DeliveryRound, Depot, Rider, RiderEndpoint, RoundRider, User

DEPOT_NAMES = {"office": "Office", "warehouse": "Warehouse"}
DESTINATION_NAMES = {"office": "Office", "warehouse": "Warehouse", "home": "Home", "last_stop": "Last stop",
                     "custom": "Custom"}
PRIVATE_KINDS = ("home", "custom")


# ------------------------------------------------------------------ locking and versions


def lock_depots_shared(db: DBSession) -> dict[str, Depot]:
    """First step of the locking order: hold both depot rows so their coordinates cannot
    change until this transaction ends."""
    rows = db.scalars(select(Depot).order_by(Depot.kind).with_for_update(read=True)).all()
    return {d.kind: d for d in rows}


def lock_round(db: DBSession, round_id: uuid.UUID) -> DeliveryRound | None:
    return db.get(DeliveryRound, round_id, with_for_update=True, populate_existing=True)


def lock_round_rider(db: DBSession, round_id: uuid.UUID, rider_id: uuid.UUID) -> RoundRider | None:
    return db.get(RoundRider, (round_id, rider_id), with_for_update=True, populate_existing=True)


def bump_round_input(db: DBSession, round_id: uuid.UUID, *, route: bool = True) -> None:
    """Record a planning-input change: `input_version` always (so any in-flight solve becomes
    stale), and `route_version` too unless the change is a rider's own delivery progress
    (`route=False`, used only by the rider status endpoint), which leaves the remaining saved
    sequence usable. Every other change keeps marking the saved plan out of date."""
    values = {"input_version": DeliveryRound.input_version + 1}
    if route:
        values["route_version"] = DeliveryRound.route_version + 1
    db.execute(update(DeliveryRound).where(DeliveryRound.id == round_id).values(**values))


def bump_config(db: DBSession, rr: RoundRider, now: datetime, *, bump_round: bool = True) -> None:
    rr.config_version += 1
    rr.updated_at = now
    if bump_round:
        bump_round_input(db, rr.round_id)


def is_confirmed(rr: RoundRider) -> bool:
    return rr.confirmed_version is not None and rr.confirmed_version == rr.config_version


def depot_users(db: DBSession, kind: str) -> list[RoundRider]:
    """Round riders whose start or destination uses this depot (any round, participating or not)."""
    as_destination = select(RiderEndpoint.rider_id).where(
        RiderEndpoint.round_id == RoundRider.round_id, RiderEndpoint.rider_id == RoundRider.rider_id,
        RiderEndpoint.kind == kind).exists()
    return list(db.scalars(
        select(RoundRider).where((RoundRider.start_kind == kind) | as_destination)
        .order_by(RoundRider.round_id, RoundRider.rider_id)).all())


# ------------------------------------------------------------------ validation


def configuration_issues(rr: RoundRider, endpoint: RiderEndpoint | None, depots: dict[str, Depot],
                         account_active: bool, area: ServiceArea) -> list[dict]:
    """What keeps this rider's current setup from being confirmable or plannable.
    Codes and plain reasons only; never coordinates."""
    issues = []
    if not account_active:
        issues.append({"code": "account_inactive",
                       "reason": "the rider's account is deactivated; remove them from this round or reactivate the account"})
    start = depots.get(rr.start_kind)
    if start is None:
        issues.append({"code": "start_depot_missing",
                       "reason": f"starts at the {DEPOT_NAMES[rr.start_kind]}, which has no location yet"})
    elif not area.contains(start.lat, start.lng):
        issues.append({"code": "start_depot_outside_area",
                       "reason": f"the {DEPOT_NAMES[rr.start_kind]} location is outside the DU North Campus service area"})
    if endpoint is None:
        issues.append({"code": "destination_missing", "reason": "has not chosen a destination"})
    elif endpoint.kind in DEPOT_NAMES:
        dest = depots.get(endpoint.kind)
        if dest is None:
            issues.append({"code": "destination_depot_missing",
                           "reason": f"chose the {DEPOT_NAMES[endpoint.kind]} as destination, which has no location yet"})
        elif not area.contains(dest.lat, dest.lng):
            issues.append({"code": "destination_depot_outside_area",
                           "reason": f"the {DEPOT_NAMES[endpoint.kind]} location is outside the DU North Campus service area"})
    elif endpoint.kind in PRIVATE_KINDS:
        if endpoint.lat is None or endpoint.lng is None or not area.contains(endpoint.lat, endpoint.lng):
            issues.append({"code": "destination_invalid",
                           "reason": f"the {DESTINATION_NAMES[endpoint.kind]} destination is not a valid location "
                                     "in the service area; the rider must choose it again"})
    return issues


def confirmation_state(rr: RoundRider) -> str:
    if is_confirmed(rr):
        return "confirmed"
    return "not_confirmed" if rr.confirmed_version is None else "outdated"


# ------------------------------------------------------------------ views


def depot_view(d: Depot, area: ServiceArea) -> dict:
    return {"kind": d.kind, "label": d.label, "lat": d.lat, "lng": d.lng, "version": d.version,
            "updated_at": d.updated_at.isoformat(), "in_service_area": area.contains(d.lat, d.lng)}


def rider_profile_view(r: Rider, u: User) -> dict:
    return {"id": str(r.id), "username": u.username, "display_name": r.display_name, "default_vehicle": r.vehicle,
            "account_active": u.active, "version": r.version}


def admin_round_rider_view(rr: RoundRider, rider: Rider, user: User, endpoint: RiderEndpoint | None,
                           depots: dict[str, Depot], area: ServiceArea) -> dict:
    """Admin view: kind and state of the destination, never its coordinates."""
    issues = configuration_issues(rr, endpoint, depots, user.active, area) if rr.participating else []
    return {
        "rider_id": str(rr.rider_id),
        "display_name": rider.display_name,
        "username": user.username,
        "account_active": user.active,
        "participating": rr.participating,
        "vehicle": rr.vehicle,
        "capacity": rr.capacity,
        "start": rr.start_kind,
        "destination": {"kind": endpoint.kind} if endpoint else None,
        "config_version": rr.config_version,
        "confirmation": {"state": confirmation_state(rr), "confirmed_version": rr.confirmed_version,
                         "confirmed_at": rr.confirmed_at.isoformat() if rr.confirmed_at else None},
        "issues": issues,
    }


def _depot_place(d: Depot | None) -> dict:
    if d is None:
        return {"set": False, "label": None, "lat": None, "lng": None}
    return {"set": True, "label": d.label, "lat": d.lat, "lng": d.lng}


def rider_config_view(rnd: DeliveryRound, rr: RoundRider, endpoint: RiderEndpoint | None,
                      depots: dict[str, Depot], area: ServiceArea) -> dict:
    """The rider's own view: everything the confirmation covers, including their own coordinates."""
    destination = None
    if endpoint is not None:
        destination = {"kind": endpoint.kind}
        if endpoint.kind in DEPOT_NAMES:
            destination |= _depot_place(depots.get(endpoint.kind))
        elif endpoint.kind in PRIVATE_KINDS:
            destination |= {"lat": endpoint.lat, "lng": endpoint.lng}
        else:
            destination |= {"open_route": True}  # Last stop: the route ends at the final delivery
    return {
        "round_id": str(rnd.id),
        "round_name": rnd.name,
        "config_version": rr.config_version,
        "vehicle": rr.vehicle,
        "capacity": rr.capacity,
        "start": {"kind": rr.start_kind} | _depot_place(depots.get(rr.start_kind)),
        "destination": destination,
        "confirmation": {"state": confirmation_state(rr), "confirmed_version": rr.confirmed_version,
                         "confirmed_at": rr.confirmed_at.isoformat() if rr.confirmed_at else None},
        "issues": configuration_issues(rr, endpoint, depots, True, area),
    }


# ------------------------------------------------------------------ readiness


def configuration_blockers(db: DBSession, round_id: uuid.UUID, area: ServiceArea) -> tuple[list[dict], dict]:
    """Rider/depot side of the planning gate: at least one participating rider, valid depots,
    starts and destinations, and a current confirmation from every participating rider."""
    depots = {d.kind: d for d in db.scalars(select(Depot)).all()}
    rows = db.execute(
        select(RoundRider, Rider, User, RiderEndpoint)
        .join(Rider, Rider.id == RoundRider.rider_id)
        .join(User, User.id == Rider.user_id)
        .outerjoin(RiderEndpoint, (RiderEndpoint.round_id == RoundRider.round_id)
                   & (RiderEndpoint.rider_id == RoundRider.rider_id))
        .where(RoundRider.round_id == round_id, RoundRider.participating.is_(True))
        .order_by(Rider.display_name, Rider.id)
    ).all()
    blockers: list[dict] = []
    if not rows:
        blockers.append({"code": "no_participating_riders", "reason": "Add at least one participating rider to this round."})
    confirmed = 0
    for rr, rider, user, endpoint in rows:
        who = {"rider_id": str(rider.id), "rider": rider.display_name}
        for issue in configuration_issues(rr, endpoint, depots, user.active, area):
            blockers.append(who | {"code": issue["code"], "reason": f"{rider.display_name}: {issue['reason']}."})
        if is_confirmed(rr):
            confirmed += 1
        elif rr.confirmed_version is None:
            blockers.append(who | {"code": "not_confirmed",
                                   "reason": f"{rider.display_name} has not confirmed their setup for this round."})
        else:
            blockers.append(who | {"code": "confirmation_outdated",
                                   "reason": f"{rider.display_name}'s setup changed after they confirmed it "
                                             "(start, vehicle, capacity, destination or a depot location); "
                                             "they must confirm again."})
    return blockers, {"participating": len(rows), "confirmed": confirmed}
