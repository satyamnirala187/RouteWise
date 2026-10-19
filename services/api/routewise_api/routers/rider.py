"""Rider endpoints: a rider sees only orders assigned to them, and only their own setup and
destination for rounds they participate in. Ownership is checked in the query itself, so
another rider's order or round is indistinguishable from a missing one (404).

Step 3A adds the read-only delivery view: the rider's own orders in a round, in the order of
the round's current plan, with only the fields a delivery needs. Step 3B adds the rider's own
status updates (Pending → Completed / Postponed, Postponed → Pending). Step 4B adds the rider's own
reroute (routewise_api/reroute.py): the delivery view follows the rider's EFFECTIVE route (their
current revision of the current plan, else the plan route), and a destination change after
planning invalidates only this rider's route (R23)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from ..config import Settings
from ..deps import CurrentUser, get_db, get_now, get_settings, require_rider
from ..locations import manual_pin
from ..models import Assignment, DeliveryRound, Depot, Order, PlanningRun, RiderEndpoint, RoundRider, RoutePlan, RouteRevision
from ..orders import order_lock_options, set_status
from .. import reroute as rr_mod
from ..rider_routes import ORIGIN_LABELS, awaiting_recalculation, effective_route, revision_view
from ..riders import (
    PRIVATE_KINDS,
    bump_own_destination,
    bump_round_input,
    configuration_issues,
    confirmation_state,
    lock_depots_shared,
    lock_round,
    lock_round_rider,
    rider_config_view,
)
from ..planning import PlanningRefused, expire_overdue, plan_validity

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
        bump_own_destination(db, rr, now)
    elif (endpoint.kind, endpoint.lat, endpoint.lng) != (body.kind, lat, lng):
        endpoint.kind, endpoint.lat, endpoint.lng, endpoint.location_source = body.kind, lat, lng, source
        endpoint.updated_at = now
        bump_own_destination(db, rr, now)  # R23: only this rider's route awaits recalculation
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
        # In-flight solves become stale; no saved route changes meaning by a confirmation alone (the
        # change being confirmed already invalidated what it had to, 4B).
        bump_round_input(db, round_id, route=False)
    return _own_view(db, rnd, rr, depots, settings)


# ------------------------------------------------------------------ delivery view (step 3A, read-only)


def _delivery_item(o: Order, area) -> dict:
    """What a rider needs to deliver one order. `location` is given only for a resolved pin
    inside the service area, so an unusable location can never become a navigation link."""
    usable = o.location_state == "resolved" and o.lat is not None and o.lng is not None and area.contains(o.lat, o.lng)
    issue = None
    if not usable:
        issue = ("This order's location needs correction by your admin." if o.location_state != "resolved"
                 else "This order's pin is outside the DU North Campus service area; ask your admin to check it.")
    return {
        "id": str(o.id), "order_code": o.order_code, "customer_name": o.customer_name, "product": o.product,
        "contact": o.contact, "instructions": o.instructions, "status": o.status, "version": o.version,
        "location": {"lat": o.lat, "lng": o.lng} if usable else None, "location_issue": issue,
    }


def _place(kind: str | None, depots: dict) -> dict | None:
    """A start or destination by kind and depot label; never coordinates."""
    if kind is None:
        return None
    d = depots.get(kind)
    return {"kind": kind, "label": d.label if d is not None else None}


def _own_rounds_with_orders(current: CurrentUser):
    return (select(Order.round_id).join(Assignment, Assignment.order_id == Order.id)
            .where(Assignment.rider_id == current.rider.id).distinct())


@router.get("/delivery-rounds")
def my_delivery_rounds(current: CurrentUser = Depends(require_rider), db: DBSession = Depends(get_db, scope="function")) -> list[dict]:
    """Rounds the rider takes part in or holds orders in (for example after leaving a round
    with Postponed or Completed orders), newest first, with their own order counts."""
    me = current.rider.id
    participating = select(RoundRider.round_id).where(RoundRider.rider_id == me, RoundRider.participating.is_(True))
    rounds = db.scalars(select(DeliveryRound)
                        .where(DeliveryRound.id.in_(participating) | DeliveryRound.id.in_(_own_rounds_with_orders(current)))
                        .order_by(DeliveryRound.created_at.desc(), DeliveryRound.id)).all()
    ids = [r.id for r in rounds]
    counts: dict = {}
    for round_id, st, n in db.execute(select(Order.round_id, Order.status, func.count())
                                      .join(Assignment, Assignment.order_id == Order.id)
                                      .where(Assignment.rider_id == me, Order.round_id.in_(ids))
                                      .group_by(Order.round_id, Order.status)).all():
        counts.setdefault(round_id, {})[st] = n
    setups = {rr.round_id: rr for rr in db.scalars(select(RoundRider).where(RoundRider.rider_id == me,
                                                                           RoundRider.round_id.in_(ids))).all()}
    planned = set(db.scalars(select(RoutePlan.round_id).where(RoutePlan.round_id.in_(ids), RoutePlan.is_current.is_(True))).all())
    out = []
    for r in rounds:
        rr = setups.get(r.id)
        joined = rr is not None and rr.participating
        c = counts.get(r.id, {})
        out.append({"round_id": str(r.id), "round_name": r.name, "participating": joined,
                    "confirmation": confirmation_state(rr) if joined else None, "has_plan": r.id in planned,
                    "orders": {"pending": c.get("Pending", 0), "postponed": c.get("Postponed", 0),
                               "completed": c.get("Completed", 0)}})
    return out


@router.get("/rounds/{round_id}/deliveries")
def my_deliveries(round_id: uuid.UUID, current: CurrentUser = Depends(require_rider),
                  db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings)) -> dict:
    """The rider's own orders in one round. Pending orders follow the round's CURRENT plan
    (never a superseded one); nothing is recalculated or reassigned here. A round the rider
    neither takes part in nor holds orders in is a 404, exactly like a missing one."""
    return _delivery_view(db, current.rider.id, round_id, settings)


def _delivery_view(db: DBSession, me: uuid.UUID, round_id: uuid.UUID, settings: Settings) -> dict:
    rnd = db.get(DeliveryRound, round_id, populate_existing=True)
    rr = db.get(RoundRider, (round_id, me)) if rnd is not None else None
    joined = rr is not None and rr.participating
    orders = db.scalars(select(Order).join(Assignment, Assignment.order_id == Order.id)
                        .where(Assignment.rider_id == me, Order.round_id == round_id)
                        .order_by(Order.order_code)).all() if rnd is not None else []
    if rnd is None or not (joined or orders):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    area = settings.service_area
    depots = {d.kind: d for d in db.scalars(select(Depot)).all()}

    plan = db.scalar(select(RoutePlan).where(RoutePlan.round_id == round_id, RoutePlan.is_current.is_(True)))
    eff = effective_route(db, plan, me) if plan is not None else None
    route = eff.plan_route if eff is not None else None
    # Only this rider's active stops in their effective route (4B: their current revision of the
    # current plan, else the plan route); ownership is re-checked below against the assignment, so
    # another rider's order can never enter this sequence.
    seq: dict = eff.sequence if eff is not None else {}
    stops: dict[int, list] = {}
    unsequenced, postponed, completed = [], [], []
    for o in orders:
        item = _delivery_item(o, area)
        if o.status == "Postponed":
            postponed.append(item)
        elif o.status == "Completed":
            completed.append(item)
        elif o.id in seq:
            stops.setdefault(seq[o.id], []).append(item)
        else:
            unsequenced.append(item)

    plan_out = None
    if plan is not None:
        plan_out = {
            "version": plan.version, "is_current": True, "created_at": plan.created_at.isoformat(),
            **plan_validity(plan, rnd), "superseded_versions": plan.version - 1,
            "real_road": bool(plan.provenance.get("real_road")), "recorded": bool(plan.provenance.get("recorded")),
            "route": None if route is None else {
                "vehicle": route.vehicle, "start": _place(route.start_kind, depots),
                "destination": _place(route.endpoint_kind, depots), "open_route": route.open_route,
                "road_distance_m": route.road_distance_m, "road_duration_s": route.road_duration_s},
            # 4B: the rider's effective route. `route` above stays the admin plan's route as saved.
            "rider_route": None if eff is None else {
                "revision": revision_view(eff.revision, {o.id: o.order_code for o in orders}),
                "origin_label": ORIGIN_LABELS[eff.revision.origin_kind] if eff.revision else None,
                "vehicle": eff.vehicle, "destination": _place(eff.endpoint_kind, depots), "open_route": eff.open_route,
                "road_distance_m": eff.road_distance_m, "road_duration_s": eff.road_duration_s,
                "awaiting_recalculation": awaiting_recalculation(eff, rr if joined else None)},
        }
    endpoint = db.get(RiderEndpoint, (round_id, me)) if joined else None
    return {
        "round_id": str(rnd.id), "round_name": rnd.name, "participating": joined,
        "setup": None if not joined else {
            "start": _place(rr.start_kind, depots), "destination": _place(endpoint.kind if endpoint else None, depots),
            "vehicle": rr.vehicle, "confirmation": confirmation_state(rr)},
        "plan": plan_out,
        "sequence": [{"seq": n, "orders": stops[n]} for n in sorted(stops)],
        "unsequenced": unsequenced, "postponed": postponed, "completed": completed,
        "reroute": _reroute_options(db, rnd.id, me, settings) if joined else None,
    }


def _reroute_options(db: DBSession, round_id: uuid.UUID, me: uuid.UUID, settings: Settings) -> dict | None:
    snap = rr_mod.capture_rider(db, round_id, me, lock=False)
    return rr_mod.reroute_options(db, snap, settings) if snap is not None else None


# ------------------------------------------------------------------ status updates (step 3B)

# The only changes a rider may make. Completed is final for riders (an admin can still edit it).
RIDER_TRANSITIONS = {("Pending", "Completed"), ("Pending", "Postponed"), ("Postponed", "Pending")}


class StatusIn(BaseModel):
    status: Literal["Pending", "Postponed", "Completed"]
    expected_version: StrictInt  # the order version the rider was shown


def _status_conflict(code: str, message: str, order: Order | None = None) -> HTTPException:
    detail = {"code": code, "message": message}
    if order is not None:  # only ever for the rider's own order
        detail |= {"current_status": order.status, "current_version": order.version}
    return HTTPException(status.HTTP_409_CONFLICT, detail)


@router.post("/orders/{order_id}/status")
def update_my_order_status(order_id: uuid.UUID, body: StatusIn, current: CurrentUser = Depends(require_rider),
                           db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
                           now: datetime = Depends(get_now)) -> dict:
    """Change the status of one of the rider's own orders and return the refreshed delivery view.

    Locks, in the order-edit order: the order row (FOR NO KEY UPDATE), then the round (FOR
    UPDATE). A plan commit holds the round lock for its whole write, so once this request has the
    round no commit is in progress, and ownership is checked again: an order a new plan has just
    given to another rider is refused (409) and nothing changes. A request that wins the round
    lock first bumps `input_version`, so the plan computed from the older input commits nothing.

    Repeats are harmless: if the order already has the requested status nothing is written and
    `changed` is false. Otherwise `expected_version` must equal the current version (409
    `order_changed` if not), so a stale request never overwrites newer rider or admin work and
    never reopens a Completed order."""
    me = current.rider.id
    # Ownership first, without locks: another rider's order is indistinguishable from a missing one.
    if db.scalar(_own_orders(current).where(Order.id == order_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    order = db.get(Order, order_id, **order_lock_options())
    rnd = lock_round(db, order.round_id)
    owner = db.scalar(select(Assignment.rider_id).where(Assignment.order_id == order_id)
                      .execution_options(populate_existing=True))
    if owner != me:
        raise _status_conflict("order_reassigned", "This order is no longer assigned to you, so nothing was changed. "
                                                   "Your list has been refreshed.")
    if order.status == body.status:
        return {"changed": False, "order": _delivery_item(order, settings.service_area),
                "view": _delivery_view(db, me, rnd.id, settings)}
    if order.version != body.expected_version:
        raise _status_conflict("order_changed", "This order was changed since you loaded it (for example by your "
                                                "admin). Nothing was overwritten; the latest status is shown.", order)
    if (order.status, body.status) not in RIDER_TRANSITIONS:
        message = ("Completed orders cannot be reopened by a rider. Ask your admin if this was a mistake."
                   if order.status == "Completed" else
                   f"A {order.status} order cannot be marked {body.status} directly.")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "transition_not_allowed", "message": message,
                                                                    "current_status": order.status})
    set_status(order, body.status, current.user.id, now)  # 4B: records when and by whom it was completed
    order.version += 1
    order.updated_at = now
    # Delivery progress: in-flight solves become stale; the remaining saved route stays usable.
    bump_round_input(db, rnd.id, route=False)
    db.flush()
    return {"changed": True, "order": _delivery_item(order, settings.service_area),
            "view": _delivery_view(db, me, rnd.id, settings)}


# ------------------------------------------------------------------ own reroute (step 4B)


class OriginIn(BaseModel):
    kind: Literal["current_position", "last_completed_stop", "configured_start"]
    # current_position only: one fresh device fix, used for this request and never stored.
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = Field(default=None, ge=0)
    age_s: float | None = Field(default=None, ge=0)
    # last_completed_stop only: the order the rider was shown as their last completed stop.
    order_id: uuid.UUID | None = None


class RerouteIn(BaseModel):
    origin: OriginIn
    expected_plan_version: StrictInt  # the plan version the rider was shown
    expected_revision: StrictInt      # their revision number shown (0 = the plan's route)


def _refused(exc: PlanningRefused) -> HTTPException:
    if exc.code == "NOT_FOUND":
        return HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return HTTPException(exc.status, exc.body())


@router.post("/rounds/{round_id}/reroute", status_code=status.HTTP_202_ACCEPTED)
def request_reroute(round_id: uuid.UUID, body: RerouteIn, request: Request, current: CurrentUser = Depends(require_rider),
                    db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
                    now: datetime = Depends(get_now)) -> dict:
    """Recalculate the order of the rider's OWN remaining Pending orders from an explicitly chosen
    origin. Refused (coded) before any work is scheduled; otherwise queued for the bounded worker
    (poll `GET /api/rider/reroutes/{id}`). See routewise_api/reroute.py."""
    me = current.rider.id
    origin = body.origin
    req = rr_mod.OriginRequest(origin.kind, origin.lat, origin.lng, origin.accuracy_m, origin.age_s, origin.order_id)
    try:
        if req.kind == "current_position":
            rr_mod.check_position(req, settings)  # before any lock; the position is never stored
        elif any(v is not None for v in (origin.lat, origin.lng, origin.accuracy_m, origin.age_s)):
            raise PlanningRefused(422, "ORIGIN_INVALID", "Only a current position carries coordinates.")
        if req.kind != "last_completed_stop" and origin.order_id is not None:
            raise PlanningRefused(422, "ORIGIN_INVALID", "Only the last completed stop names an order.")
    except PlanningRefused as exc:
        raise _refused(exc) from None
    service = request.app.state.planning
    lock_depots_shared(db)
    if lock_round(db, round_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    if lock_round_rider(db, round_id, me) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    snap = rr_mod.capture_rider(db, round_id, me)
    try:
        refusal = rr_mod.refusal_for_state(snap, rr_mod.active_round_run(db, round_id) is not None)
        if refusal is not None:
            raise refusal
        running = rr_mod.active_rider_run(db, round_id, me)
        if running is not None:
            raise PlanningRefused(409, "REROUTE_IN_PROGRESS", "Your route is already being recalculated.", [str(running.id)])
        if (body.expected_plan_version, body.expected_revision) != (snap.base_plan_version, snap.revision):
            raise PlanningRefused(409, "ROUTE_CHANGED", "Your route changed since you loaded it. Review it and choose again.")
        prepared = rr_mod.prepare_rider(snap, rr_mod.resolve_origin(snap, req, settings), settings)
        try:
            service.provider()
        except Exception:
            raise PlanningRefused(503, "ROUTING_ENGINE_UNAVAILABLE", "Local road routing is not available on this "
                                  "server. Your current route is unchanged.") from None
    except PlanningRefused as exc:
        raise _refused(exc) from None
    if not service.try_reserve():
        raise HTTPException(503, {"code": "PLANNING_BUSY", "message": "The planner is busy; try again in a moment. "
                                  "Your current route is unchanged.", "details": []})
    try:
        run = PlanningRun(round_id=round_id, state="queued", requested_by=current.user.id, requested_at=now,
                          input_version=snap.input_version, input_fingerprint=rr_mod.rider_fingerprint(snap, settings.secret_key),
                          mode=db.get(DeliveryRound, round_id).mode, scope="rider", rider_id=me,
                          base_plan_id=snap.base_plan_id, origin_kind=prepared.origin.kind)
        db.add(run)
        db.commit()  # visible to the worker before it is queued; get_db's own commit is then a no-op
    except IntegrityError:
        db.rollback()
        service.release()
        raise HTTPException(409, {"code": "REROUTE_IN_PROGRESS", "message": "Your route is already being recalculated.",
                                  "details": []}) from None
    except BaseException:
        service.release()
        raise
    service.submit(run.id, snap, prepared, runner=lambda job: rr_mod.run_rider(service, job))
    return rr_mod.run_view(run)


@router.get("/reroutes/{run_id}")
def my_reroute(run_id: uuid.UUID, current: CurrentUser = Depends(require_rider),
               db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
               now: datetime = Depends(get_now)) -> dict:
    """The rider's own reroute run; another rider's run is indistinguishable from a missing one."""
    run = db.get(PlanningRun, run_id)
    if run is None or run.scope != "rider" or run.rider_id != current.rider.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    expire_overdue(db, run, now, settings.planning.stale_after_s)
    revision = db.scalar(select(RouteRevision.revision).where(RouteRevision.run_id == run.id))
    return rr_mod.run_view(run, revision)
