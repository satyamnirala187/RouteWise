"""Step 4B: a rider recalculates the order of their OWN remaining Pending orders.

What it changes and what it never changes. A reroute writes exactly one new `route_revisions`
row (plus its `revision_orders`) for the requesting rider on top of the round's current plan, and
marks that rider's previous revision for the same plan superseded. It never writes `route_plans`,
`plan_routes`, `plan_orders`, `assignments`, any order, or anything of another rider. Ownership
is not an input: only orders the rider already owns (through `assignments`) are sequenced, and
only Pending ones. Postponed orders stay with the rider, off the sequence, until the rider returns
them to Pending (D08); Completed orders are history.

Flow (same shape as planning.py). The request takes the documented locks (depots FOR SHARE →
round FOR UPDATE → the rider's own round_riders row FOR UPDATE), refuses with a coded reason
before any work is scheduled, captures a RIDER-SCOPED snapshot in memory and its keyed
fingerprint, stores a `queued` rider run and hands it to the bounded worker. The worker builds a
local Valhalla matrix and solves one vehicle with no database transaction open. The commit takes
the same locks again, recaptures the rider-scoped input and saves the revision only if the round's
current plan is still the base plan and the fingerprint is unchanged; otherwise the run ends
`stale` and the rider's last valid route is kept.

Why rider-scoped. The fingerprint covers what this rider's route depends on: the base plan and
the rider's current revision; the round's and the rider's route versions; the rider's account
state, participation, confirmation and configuration (vehicle, capacity, start, destination,
including the depot coordinates their start and destination use); and every order the rider owns
in the round (status, pin, lock, priority, completion record, stop group (4C)). It does NOT include the round's
`input_version`, so another rider's delivery progress or own reroute never makes this one stale.

Origins are explicit and labelled; none is chosen for the rider:
- `current_position`: one fresh device fix sent with this request; refused if less accurate than
  `RerouteLimits.gps_max_accuracy_m`, older than `gps_max_age_s`, non-finite, or outside the
  service area. Never stored, logged or reused.
- `last_completed_stop`: the rider's own most recently completed order in this round, as recorded
  by the 4B completion timestamp (an order the rider marked Completed). The request names the
  order it was shown; a newer completion makes it `ORIGIN_CHANGED`.
- `configured_start`: the rider's Office/Warehouse start, allowed only when no completed stop
  exists (working flow §7), and labelled as not the current position.
The limits are provisional local defaults, configurable (config.RerouteLimits).

Stop groups (4C). The rider's snapshot holds only the rider's OWN orders, so a reroute groups only
their own Pending orders: another rider's order that shares the building is never seen, moved or
shown. The remaining Pending customers of a partly delivered building stay one stop.

Privacy. Positions, Home/Custom coordinates and pins live only in request memory and the
worker's snapshot. Runs, revisions, errors and logs carry ids, kinds and order codes only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from .config import Settings
from .models import (
    ACTIVE_RUN_STATES,
    Assignment,
    DeliveryRound,
    Depot,
    Order,
    PlanningRun,
    PlanRoute,
    RevisionOrder,
    Rider,
    RiderEndpoint,
    RoundRider,
    RoutePlan,
    RouteRevision,
    User,
)
from .planning import VEHICLE_PROFILE, PlanningRefused, _finish, _TimedProvider
from .rider_routes import ORIGIN_LABELS, awaiting_recalculation, current_revision, effective_route
from .riders import is_confirmed, lock_depots_shared, lock_round, lock_round_rider
from .routing import planner
from .routing import reroute as rider_solver
from .routing.domain import EndpointKind, Location, Vehicle
from .routing.domain import Order as DomainOrder
from .routing.matrix.base import ProviderError

log = logging.getLogger("routewise.reroute")


# ------------------------------------------------------------------ snapshot


@dataclass(frozen=True)
class OwnOrder:
    id: uuid.UUID
    order_code: str
    customer_name: str  # shown to the rider only (fallback label); not part of the fingerprint
    status: str
    location_state: str
    lat: float | None
    lng: float | None
    locked_rider_id: uuid.UUID | None
    first_priority: bool
    completed_at: datetime | None
    completed_by: uuid.UUID | None
    building_id: str | None = None  # 4C: admin-confirmed stop group; only the rider's OWN orders are loaded


@dataclass(frozen=True)
class RiderSnapshot:
    round_id: uuid.UUID
    rider_id: uuid.UUID
    user_id: uuid.UUID
    base_plan_id: uuid.UUID | None
    base_plan_version: int | None
    has_plan_route: bool
    revision: int                      # the rider's current revision number for the base plan (0 = plan route)
    effective_rider_route_version: int | None
    round_route_version: int
    plan_round_route_version: int | None
    rider_route_version: int
    input_version: int                 # informational only; never compared (other riders' progress moves it)
    account_active: bool
    participating: bool
    confirmed: bool
    config_version: int
    vehicle: str
    capacity: int
    start_kind: str
    endpoint_kind: str | None
    endpoint_lat: float | None
    endpoint_lng: float | None
    depots: tuple[tuple[str, float, float], ...]  # only the depots this rider's start/destination use
    orders: tuple[OwnOrder, ...]       # every order the rider owns in this round

    def pending(self) -> list[OwnOrder]:
        return [o for o in self.orders if o.status == "Pending"]

    def held(self) -> int:
        return sum(1 for o in self.orders if o.status != "Pending")


def capture_rider(db: DBSession, round_id: uuid.UUID, rider_id: uuid.UUID, *, lock: bool = True) -> RiderSnapshot | None:
    """The rider-scoped planning input. For a request or commit (`lock`), the caller holds the
    depot, round and own round-rider locks, and the rider's user row is read FOR SHARE so a
    deactivation waits. Read-only views pass lock=False. None if the rider is not in the round."""
    rnd = db.get(DeliveryRound, round_id, populate_existing=True)
    q = (select(RoundRider, Rider, User, RiderEndpoint)
         .join(Rider, Rider.id == RoundRider.rider_id)
         .join(User, User.id == Rider.user_id)
         .outerjoin(RiderEndpoint, (RiderEndpoint.round_id == RoundRider.round_id)
                    & (RiderEndpoint.rider_id == RoundRider.rider_id))
         .where(RoundRider.round_id == round_id, RoundRider.rider_id == rider_id))
    if lock:
        q = q.with_for_update(read=True, of=User)
    row = db.execute(q.execution_options(populate_existing=True)).first()
    if rnd is None or row is None:
        return None
    rr, rider, user, endpoint = row
    used = {rr.start_kind} | ({endpoint.kind} if endpoint is not None and endpoint.kind in ("office", "warehouse") else set())
    depots = tuple((d.kind, d.lat, d.lng) for d in db.scalars(select(Depot).where(Depot.kind.in_(sorted(used)))
                                                               .order_by(Depot.kind)).all())
    plan = db.scalar(select(RoutePlan).where(RoutePlan.round_id == round_id, RoutePlan.is_current.is_(True))
                     .execution_options(populate_existing=True))
    eff = effective_route(db, plan, rider_id) if plan is not None else None
    rows = db.execute(
        select(Order).join(Assignment, Assignment.order_id == Order.id)
        .where(Assignment.rider_id == rider_id, Order.round_id == round_id)
        .order_by(Order.id).execution_options(populate_existing=True)).scalars().all()
    orders = tuple(OwnOrder(o.id, o.order_code, o.customer_name, o.status, o.location_state, o.lat, o.lng,
                            o.locked_rider_id, o.first_priority, o.completed_at, o.completed_by, o.building_id)
                  for o in rows)
    return RiderSnapshot(
        round_id=round_id, rider_id=rider_id, user_id=user.id,
        base_plan_id=plan.id if plan else None, base_plan_version=plan.version if plan else None,
        has_plan_route=eff is not None, revision=eff.revision_number if eff else 0,
        effective_rider_route_version=eff.rider_route_version if eff else None,
        round_route_version=rnd.route_version, plan_round_route_version=plan.route_version if plan else None,
        rider_route_version=rr.route_version, input_version=rnd.input_version,
        account_active=user.active, participating=rr.participating, confirmed=is_confirmed(rr),
        config_version=rr.config_version, vehicle=rr.vehicle, capacity=rr.capacity, start_kind=rr.start_kind,
        endpoint_kind=endpoint.kind if endpoint else None, endpoint_lat=endpoint.lat if endpoint else None,
        endpoint_lng=endpoint.lng if endpoint else None, depots=depots, orders=orders)


def rider_fingerprint(snap: RiderSnapshot, secret: str) -> str:
    """Keyed digest of the rider-scoped input (keyed, so a Home location cannot be guessed back)."""
    t = lambda v: v.isoformat() if isinstance(v, datetime) else (str(v) if isinstance(v, uuid.UUID) else v)  # noqa: E731
    state = {
        "round": str(snap.round_id), "rider": str(snap.rider_id),
        "plan": [t(snap.base_plan_id), snap.revision, snap.round_route_version, snap.rider_route_version],
        "rider_state": [snap.account_active, snap.participating, snap.confirmed, snap.config_version, snap.vehicle,
                        snap.capacity, snap.start_kind, snap.endpoint_kind, snap.endpoint_lat, snap.endpoint_lng],
        "depots": snap.depots,
        "orders": [[str(o.id), o.status, o.location_state, o.lat, o.lng, t(o.locked_rider_id), o.first_priority,
                    t(o.completed_at), t(o.completed_by), o.building_id] for o in snap.orders],
    }
    payload = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), b"routewise-reroute-input\0" + payload, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ origins


@dataclass(frozen=True)
class OriginRequest:
    kind: str
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None
    age_s: float | None = None
    order_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Origin:
    kind: str
    lat: float
    lng: float
    order_id: uuid.UUID | None
    order_code: str | None


def _usable(o: OwnOrder, settings: Settings) -> bool:
    return (o.location_state == "resolved" and o.lat is not None and o.lng is not None
            and settings.service_area.contains(o.lat, o.lng))


def last_completed_stop(snap: RiderSnapshot, settings: Settings) -> OwnOrder | None:
    """The rider's own most recent completion in this round, as recorded since 4B (completed by
    this rider's account, with a usable pin). Completions without a recorded time are never used."""
    done = [o for o in snap.orders if o.status == "Completed" and o.completed_at is not None
            and o.completed_by == snap.user_id and _usable(o, settings)]
    return max(done, key=lambda o: (o.completed_at, o.order_code)) if done else None


def check_position(req: OriginRequest, settings: Settings) -> None:
    """Validate a device fix before any lock is taken. The message never echoes the position."""
    limits = settings.reroute
    values = (req.lat, req.lng, req.accuracy_m, req.age_s)
    if any(v is None or not math.isfinite(v) for v in values):
        raise PlanningRefused(422, "POSITION_UNUSABLE", "The device position is incomplete. Try again or choose "
                              "another starting point.")
    if not (-90 <= req.lat <= 90 and -180 <= req.lng <= 180) or req.accuracy_m < 0 or req.age_s < 0:
        raise PlanningRefused(422, "POSITION_UNUSABLE", "The device position is not valid. Try again or choose "
                              "another starting point.")
    if req.accuracy_m > limits.gps_max_accuracy_m:
        raise PlanningRefused(422, "POSITION_UNUSABLE", f"The device position is accurate only to about "
                              f"{round(req.accuracy_m)} m (the limit is {round(limits.gps_max_accuracy_m)} m). "
                              "Try again outdoors or choose another starting point.")
    if req.age_s > limits.gps_max_age_s:
        raise PlanningRefused(422, "POSITION_UNUSABLE", f"The device position is {round(req.age_s)} s old (the limit "
                              f"is {round(limits.gps_max_age_s)} s). Get a fresh position or choose another starting point.")
    if not settings.service_area.contains(req.lat, req.lng):
        raise PlanningRefused(422, "POSITION_UNUSABLE", "Your position is outside the DU North Campus service area "
                              "that local routing covers. Choose another starting point.")


def resolve_origin(snap: RiderSnapshot, req: OriginRequest, settings: Settings) -> Origin:
    """Turn the rider's explicit choice into an origin, or refuse with a coded reason."""
    last = last_completed_stop(snap, settings)
    if req.kind == "current_position":
        return Origin("current_position", req.lat, req.lng, None, None)
    if req.kind == "last_completed_stop":
        if last is None:
            raise PlanningRefused(422, "NO_COMPLETED_STOP", "You have no completed stop in this round with a recorded "
                                  "completion time. Use your current position or your configured start.")
        if req.order_id != last.id:
            raise PlanningRefused(409, "ORIGIN_CHANGED", "Your last completed stop is no longer the one you were shown. "
                                  "Review the latest one and choose again.", [last.order_code])
        return Origin("last_completed_stop", last.lat, last.lng, last.id, last.order_code)
    if req.kind == "configured_start":
        if last is not None:
            raise PlanningRefused(409, "COMPLETED_STOP_AVAILABLE", "You have a completed stop in this round: start "
                                  "from it or from your current position, not from your configured start.",
                                  [last.order_code])
        depot = {k: (lat, lng) for k, lat, lng in snap.depots}.get(snap.start_kind)
        if depot is None or not settings.service_area.contains(*depot):
            raise PlanningRefused(409, "CONFIGURATION_NOT_READY", "Your configured start has no valid location.")
        return Origin("configured_start", depot[0], depot[1], None, None)
    raise PlanningRefused(422, "ORIGIN_INVALID", "Choose a starting point.")


# ------------------------------------------------------------------ prechecks


@dataclass
class RiderPrepared:
    inp: rider_solver.RerouteInput
    origin: Origin
    trigger: str
    pending: list[OwnOrder]
    held: int
    points: int


def refusal_for_state(snap: RiderSnapshot, active_round_run: bool) -> PlanningRefused | None:
    """Why this rider cannot reroute right now, before the origin is considered (also shown in the
    delivery view so the rider is told up front). None if a reroute may be requested."""
    if not snap.participating:
        return PlanningRefused(404, "NOT_FOUND", "Round not found")
    if not snap.account_active:
        return PlanningRefused(409, "ACCOUNT_INACTIVE", "Your account is not active.")
    if active_round_run:
        return PlanningRefused(409, "ROUND_REPLANNING", "Your admin is replanning the round. Try again when it "
                               "finishes; your current route is unchanged.")
    if snap.base_plan_id is None:
        return PlanningRefused(409, "NO_PLAN", "No route has been planned for this round yet.")
    if not snap.has_plan_route:
        return PlanningRefused(409, "NOT_IN_PLAN", "The current plan has no route for you. Ask your admin to "
                               "optimize the round again.")
    if snap.plan_round_route_version != snap.round_route_version:
        return PlanningRefused(409, "ROUND_OUT_OF_DATE", "The round changed after it was planned. Ask your admin to "
                               "optimize the round again.")
    if not snap.confirmed or snap.endpoint_kind is None:
        return PlanningRefused(409, "NOT_CONFIRMED", "Confirm your setup for this round first.")
    if not snap.pending():
        return PlanningRefused(422, "NOTHING_TO_REROUTE", "You have no Pending orders to recalculate.")
    return None


def prepare_rider(snap: RiderSnapshot, origin: Origin, settings: Settings) -> RiderPrepared:
    """Every check that needs no road data. Raises PlanningRefused; never changes anything."""
    pending = snap.pending()
    bad = [o.order_code for o in pending if not _usable(o, settings)]
    if bad:
        raise PlanningRefused(409, "ORDERS_NOT_READY", "Some of your orders need a valid pin from your admin.", bad)
    foreign_lock = [o.order_code for o in pending if o.locked_rider_id not in (None, snap.rider_id)]
    if foreign_lock:
        raise PlanningRefused(409, "ROUND_OUT_OF_DATE", "Some of your orders are locked to another rider. Ask your "
                              "admin to optimize the round again.", foreign_lock)
    held = snap.held()
    if held + len(pending) > snap.capacity:
        raise PlanningRefused(422, "HELD_ORDERS_EXCEED_CAPACITY", "Your orders exceed your capacity for this round. "
                              "Ask your admin.")
    if len(pending) > settings.planning.max_pending_orders:
        raise PlanningRefused(422, "ROUND_TOO_LARGE", f"More than {settings.planning.max_pending_orders} Pending orders.")

    points: dict[tuple[float, float], str] = {}
    locations: dict[str, Location] = {}

    def loc(lat: float, lng: float) -> str:  # identical coordinates share one road point
        if (lat, lng) not in points:
            points[(lat, lng)] = f"L{len(points)}"
            locations[points[(lat, lng)]] = Location(points[(lat, lng)], "", lat, lng)
        return points[(lat, lng)]

    origin_id = loc(origin.lat, origin.lng)
    depots = {k: (lat, lng) for k, lat, lng in snap.depots}
    if snap.endpoint_kind == "last_stop":
        end_id = None
    elif snap.endpoint_kind in ("office", "warehouse"):
        if snap.endpoint_kind not in depots:
            raise PlanningRefused(409, "CONFIGURATION_NOT_READY", "Your destination has no location.")
        end_id = loc(*depots[snap.endpoint_kind])
    else:
        if snap.endpoint_lat is None:
            raise PlanningRefused(409, "CONFIGURATION_NOT_READY", "Your destination has no location.")
        end_id = loc(snap.endpoint_lat, snap.endpoint_lng)
    orders = tuple(DomainOrder(id=o.order_code, location_id=loc(o.lat, o.lng), building_id=o.building_id,
                               locked_rider_id=str(o.locked_rider_id) if o.locked_rider_id else None,
                               first_priority=o.first_priority) for o in pending)
    if len(points) > settings.planning.max_locations:
        raise PlanningRefused(422, "ROUND_TOO_LARGE", f"More than {settings.planning.max_locations} road points.")
    inp = rider_solver.RerouteInput(
        rider_id=str(snap.rider_id), vehicle=Vehicle(snap.vehicle), capacity=snap.capacity - held,
        origin_id=origin_id, end_id=end_id, endpoint_kind=EndpointKind(snap.endpoint_kind), orders=orders,
        locations=locations)
    try:
        rider_solver.stops_for(inp)
    except planner.PlanningError as exc:  # PRIORITY_CONFLICT
        raise PlanningRefused(422, exc.code, exc.message, exc.details) from None
    trigger = "endpoint_change" if snap.effective_rider_route_version != snap.rider_route_version else "rider_request"
    return RiderPrepared(inp, origin, trigger, pending, held, len(points))


def active_round_run(db: DBSession, round_id: uuid.UUID) -> PlanningRun | None:
    return db.scalar(select(PlanningRun).where(PlanningRun.round_id == round_id, PlanningRun.scope == "round",
                                               PlanningRun.state.in_(ACTIVE_RUN_STATES)))


def active_rider_run(db: DBSession, round_id: uuid.UUID, rider_id: uuid.UUID) -> PlanningRun | None:
    return db.scalar(select(PlanningRun).where(PlanningRun.round_id == round_id, PlanningRun.scope == "rider",
                                               PlanningRun.rider_id == rider_id, PlanningRun.state.in_(ACTIVE_RUN_STATES)))


# ------------------------------------------------------------------ solving (no database)


@dataclass
class RiderSolved:
    result: rider_solver.RerouteResult
    timings: dict


def solve_rider(prepared: RiderPrepared, provider, settings: Settings) -> RiderSolved:
    timed = _TimedProvider(provider)
    t0 = time.monotonic()
    result = rider_solver.reroute(prepared.inp, timed, profile=VEHICLE_PROFILE[prepared.inp.vehicle.value],
                                  metric="distance", time_limit_s=settings.reroute.solve_seconds)
    total = time.monotonic() - t0
    return RiderSolved(result, {"matrix_s": round(timed.seconds, 3), "solve_s": round(total - timed.seconds, 3),
                                "total_s": round(total, 3), "matrix_calls": timed.calls, "points": prepared.points,
                                "pending_orders": len(prepared.pending)})


# ------------------------------------------------------------------ commit


def _round_assignments(db: DBSession, round_id: uuid.UUID) -> list[tuple]:
    return sorted(db.execute(select(Assignment.order_id, Assignment.rider_id, Assignment.plan_id, Assignment.assigned_at)
                             .join(Order, Order.id == Assignment.order_id).where(Order.round_id == round_id)
                             .execution_options(populate_existing=True)).all())


def commit_revision(db: DBSession, run_id: uuid.UUID, snap: RiderSnapshot, prepared: RiderPrepared,
                    solved: RiderSolved, secret: str, now: datetime, before_write=None) -> str:
    """Save the revision atomically if, under lock, the rider-scoped input is still exactly the
    snapshot's and the base plan is still current. Returns the run's final state; the caller
    commits or rolls back `db`. `before_write` (tests only) runs after the final check."""
    lock_depots_shared(db)
    if lock_round(db, snap.round_id) is None:
        return "missing"
    lock_round_rider(db, snap.round_id, snap.rider_id)
    run = db.get(PlanningRun, run_id, with_for_update=True, populate_existing=True)
    if run is None or run.state != "running":
        return run.state if run is not None else "missing"
    run.timings = solved.timings
    fresh = capture_rider(db, snap.round_id, snap.rider_id)
    if fresh is None or fresh.base_plan_id != run.base_plan_id:
        _finish(run, "stale", now, "ROUND_REPLANNED", "Your admin replanned the round while your route was being "
                "recalculated. Nothing was saved; your route is the new plan's route.")
        return "stale"
    if rider_fingerprint(fresh, secret) != run.input_fingerprint:
        _finish(run, "stale", now, "INPUTS_CHANGED", "Your orders or setup changed while your route was being "
                "recalculated. Nothing was saved; your previous route is kept. Try again.")
        return "stale"
    if before_write is not None:
        before_write(run_id)

    assignments_before = _round_assignments(db, snap.round_id)
    previous = current_revision(db, snap.base_plan_id, snap.rider_id, lock=True)
    number = (db.scalar(select(func.max(RouteRevision.revision)).where(RouteRevision.plan_id == snap.base_plan_id,
                                                                        RouteRevision.rider_id == snap.rider_id)) or 0) + 1
    if previous is not None:
        previous.is_current, previous.superseded_at = False, now
        db.flush()  # one current revision per rider and plan
    route = solved.result.route
    provenance = solved.result.provenance.as_dict() | {"solver_strategy": solved.result.solve.strategy,
                                                        "solver_status": solved.result.solve.status, "metric": "distance"}
    rev = RouteRevision(
        round_id=snap.round_id, plan_id=snap.base_plan_id, rider_id=snap.rider_id, revision=number, run_id=run.id,
        is_current=True, trigger=prepared.trigger, origin_kind=prepared.origin.kind,
        origin_order_id=prepared.origin.order_id, vehicle=snap.vehicle, profile=VEHICLE_PROFILE[snap.vehicle],
        capacity=snap.capacity, endpoint_kind=snap.endpoint_kind, open_route=route.end_location_id is None,
        road_distance_m=route.road_distance_m, road_duration_s=route.road_duration_s,
        rider_route_version=fresh.rider_route_version, round_route_version=fresh.round_route_version,
        input_fingerprint=run.input_fingerprint, provenance=provenance, created_by=run.requested_by, created_at=now)
    db.add(rev)
    db.flush()
    by_code = {o.order_code: o.id for o in snap.pending()}
    for seq, stop in enumerate(route.stops, start=1):
        for code in stop.order_ids:
            db.add(RevisionOrder(revision_id=rev.id, order_id=by_code[code], stop_seq=seq))
    db.flush()

    # Independent re-read before the transaction can commit.
    sequenced = set(db.scalars(select(RevisionOrder.order_id).where(RevisionOrder.revision_id == rev.id)).all())
    owned_pending = set(db.scalars(select(Order.id).join(Assignment, Assignment.order_id == Order.id)
                                   .where(Assignment.rider_id == snap.rider_id, Order.round_id == snap.round_id,
                                          Order.status == "Pending").execution_options(populate_existing=True)).all())
    if sequenced != owned_pending or sequenced != set(by_code.values()):
        raise RuntimeError("revision does not cover exactly the rider's own Pending orders")
    if _round_assignments(db, snap.round_id) != assignments_before:
        raise RuntimeError("a reroute changed assignments")
    _finish(run, "succeeded", now)
    return "succeeded"


def run_rider(service, job) -> None:
    """Worker body for a rider run (same states and failure handling as a round run)."""
    if not service._set(job.run_id, "running", expect=("queued",)):
        return
    try:
        solved = solve_rider(job.prepared, service.provider(), service.settings)
    except planner.PlanningError as exc:
        log.info("rider run %s failed: %s", job.run_id, exc.code)
        service._set(job.run_id, "failed", expect=("running",), code=exc.code, message=exc.message,
                     details=list(exc.details))
        return
    except ProviderError as exc:
        log.warning("rider run %s: routing engine unavailable (%s)", job.run_id, type(exc).__name__)
        service._set(job.run_id, "failed", expect=("running",), code="ROUTING_ENGINE_UNAVAILABLE",
                     message="The local road-routing engine failed. Nothing was saved; your current route is unchanged.")
        return
    except Exception as exc:
        log.error("rider run %s: unexpected %s", job.run_id, type(exc).__name__)
        service._set(job.run_id, "failed", expect=("running",), code="INTERNAL",
                     message="Recalculating failed unexpectedly. Nothing was saved; your current route is unchanged.")
        return
    hook = service.hooks.get("after_solve")
    if hook:
        hook(job.run_id)
    try:
        with service.session_factory() as db:
            state = commit_revision(db, job.run_id, job.snap, job.prepared, solved, service.settings.secret_key,
                                    service.clock(), before_write=service.hooks.get("before_write"))
            db.commit()
        log.info("rider run %s: %s", job.run_id, state)
    except Exception as exc:
        log.error("rider run %s: commit failed (%s)", job.run_id, type(exc).__name__)
        service._set(job.run_id, "failed", expect=("running",), code="INTERNAL",
                     message="Saving the recalculated route failed. Nothing was saved; your current route is unchanged.")


# ------------------------------------------------------------------ views


def run_view(run: PlanningRun, revision: int | None = None) -> dict:
    return {
        "id": str(run.id), "round_id": str(run.round_id), "state": run.state, "origin_kind": run.origin_kind,
        "requested_at": run.requested_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": ({"code": run.error_code, "message": run.error_message, "details": run.error_details or []}
                  if run.error_code else None),
        "revision": revision,
    }


def reroute_options(db: DBSession, snap: RiderSnapshot, settings: Settings) -> dict:
    """What the rider may choose right now (delivery view). Kinds and order codes only."""
    refusal = refusal_for_state(snap, active_round_run(db, snap.round_id) is not None)
    last = last_completed_stop(snap, settings)
    running = active_rider_run(db, snap.round_id, snap.rider_id)
    return {
        "available": refusal is None and running is None,
        "blocked": None if refusal is None else {"code": refusal.code, "message": refusal.message},
        "in_progress_run_id": str(running.id) if running else None,
        "last_completed_stop": ({"order_id": str(last.id), "order_code": last.order_code,
                                 "customer_name": last.customer_name, "label": ORIGIN_LABELS["last_completed_stop"]}
                                if last else None),
        "configured_start_allowed": last is None,
        "gps_limits": {"max_accuracy_m": settings.reroute.gps_max_accuracy_m, "max_age_s": settings.reroute.gps_max_age_s},
    }


__all__ = ["OriginRequest", "RiderSnapshot", "awaiting_recalculation", "capture_rider", "check_position",
           "commit_revision", "prepare_rider", "refusal_for_state", "resolve_origin", "rider_fingerprint",
           "run_rider", "run_view", "reroute_options"]
