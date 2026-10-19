"""Phase 2B: planning snapshot, prechecks, bounded background worker and atomic plan commit.

Flow. `POST /optimize` locks the round's planning input (depots FOR SHARE → round FOR UPDATE),
checks every gate, captures an in-memory snapshot and its keyed fingerprint, stores a `queued`
run and hands the snapshot to a worker thread. The worker computes local Valhalla matrices
and solves with OR-Tools **without any open database transaction**. It then takes the same
locks again, recaptures the input and commits the plan only if both the round's
`input_version` and the fingerprint are unchanged; otherwise the run ends `stale` and the
previous plan and assignments stay exactly as they were.

Route validity (3B). Every status change bumps `input_version`, so a solve that started before
it is stale. A rider's own delivery progress does not bump the round's `route_version`, which
each committed plan records: the remaining saved sequence stays usable. Any other input change
bumps both, and the saved plan is reported out of date (see models.DeliveryRound).

Statuses. Only Pending orders are planned. Postponed orders keep their existing owner and stay
off the active sequence; Completed orders keep their history and owner. Anything that would
reset or reassign a Postponed or Completed order is refused with a coded "unsupported" error
and nothing is changed (operational rerouting is Phase 4).

Lock order (shared with 2A and the Phase 1 order edits):
  configuration writes, confirmations, optimize requests, plan commits:
      depots (FOR SHARE; a depot edit takes FOR UPDATE) → round (FOR UPDATE) → round-rider / run rows
  order edits (pins, statuses, text, locks, priority) and rider status updates (3B):
      order rows (FOR NO KEY UPDATE, sorted by id) → round (UPDATE of input_version; the rider
      endpoint takes the round FOR UPDATE first and re-checks ownership under it)
  account deactivation (`accounts.deactivate_user`):
      depots (FOR SHARE) → every round the rider participates in (FOR UPDATE, sorted) → user (FOR UPDATE)
Plan commits never lock order rows; their foreign keys take KEY SHARE, which does not conflict
with FOR NO KEY UPDATE, so no wait cycle exists between the two groups. `capture` reads the
participating riders' user rows FOR SHARE after the round lock, so account state cannot change
between the final check and the commit.

The explicit round lock in `commit_plan` is what makes the final check meaningful: an input edit
needs that row (every edit bumps `input_version` under it), so once the check has passed no edit
can commit until the plan and its assignments are committed, and the edit then marks the new
plan out of date. Without it, an edit could commit between the check and the writes, and the
plan would overwrite assignments with a result computed from older input.

Rider reroutes (4B, routewise_api/reroute.py) run in the same bounded worker as rider-scoped runs
and commit a route revision under the same depot → round lock order (then the rider's own
round-rider row). A round plan commit supersedes every rider revision of the plan it replaces.

Privacy. Snapshots (with Home/Custom coordinates) exist only in memory. Runs, plans, errors and
logs carry order codes, rider ids/names and kinds, never destination coordinates.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session as DBSession

from .config import PlanningLimits, Settings
from .models import (
    ACTIVE_RUN_STATES,
    Assignment,
    DeliveryRound,
    Depot,
    Order,
    PlanningRun,
    PlanOrder,
    PlanRoute,
    Rider,
    RiderEndpoint,
    RoundRider,
    RoutePlan,
    RouteRevision,
    User,
)
from .orders import readiness_blockers
from .riders import is_confirmed, lock_depots_shared, lock_round
from .routing import planner
from .routing.domain import (
    DeliveryRound as DomainRound,
)
from .routing.domain import (
    Depots,
    DistributionMode,
    Endpoint,
    EndpointKind,
    Location,
    StartKind,
    Vehicle,
)
from .routing.domain import (
    Order as DomainOrder,
)
from .routing.domain import (
    Rider as DomainRider,
)
from .routing.matrix.base import ProviderError, RoadMatrix
from .routing.matrix.valhalla_local import ValhallaLocalProvider

log = logging.getLogger("routewise.planning")

VEHICLE_PROFILE = {"scooter": "motor_scooter", "bike": "motorcycle"}  # never bicycle, auto or car
DOMAIN_PROFILE = {Vehicle.SCOOTER: "motor_scooter", Vehicle.BIKE: "motorcycle"}


class PlanningRefused(Exception):
    """A coded refusal before any work is scheduled (or when a worker re-validates)."""

    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        super().__init__(f"{code}: {message}")
        self.status, self.code, self.message, self.details = status, code, message, details or []

    def body(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


# ------------------------------------------------------------------ snapshot


@dataclass(frozen=True)
class OrderSnap:
    id: uuid.UUID
    order_code: str
    status: str
    location_state: str
    lat: float | None
    lng: float | None
    locked_rider_id: uuid.UUID | None
    first_priority: bool
    owner_rider_id: uuid.UUID | None
    building_id: None = None  # same-building grouping is Phase 4; never grouped here


@dataclass(frozen=True)
class RiderSnap:
    rider_id: uuid.UUID
    display_name: str
    account_active: bool
    vehicle: str
    capacity: int
    start_kind: str
    config_version: int
    route_version: int  # 4B: rider-scoped route validity, recorded on the plan route
    confirmed: bool
    endpoint_kind: str | None
    endpoint_lat: float | None
    endpoint_lng: float | None


@dataclass(frozen=True)
class Snapshot:
    round_id: uuid.UUID
    input_version: int
    mode: str
    depots: tuple[tuple[str, float, float], ...]
    riders: tuple[RiderSnap, ...]
    orders: tuple[OrderSnap, ...]

    def rider_names(self) -> dict[str, str]:
        return {str(r.rider_id): r.display_name for r in self.riders}


def capture(db: DBSession, round_id: uuid.UUID) -> Snapshot:
    """Read every planning input of a round. The caller holds the depot and round locks, so
    the planning-relevant state cannot change underneath (order edits wait on the round row);
    participating riders' user rows are taken FOR SHARE so a deactivation waits as well."""
    rnd = db.get(DeliveryRound, round_id, populate_existing=True)
    depots = tuple((d.kind, d.lat, d.lng) for d in db.scalars(select(Depot).order_by(Depot.kind)).all())
    rider_rows = db.execute(
        select(RoundRider, Rider, User, RiderEndpoint)
        .join(Rider, Rider.id == RoundRider.rider_id)
        .join(User, User.id == Rider.user_id)
        .outerjoin(RiderEndpoint, (RiderEndpoint.round_id == RoundRider.round_id)
                   & (RiderEndpoint.rider_id == RoundRider.rider_id))
        .where(RoundRider.round_id == round_id, RoundRider.participating.is_(True))
        .order_by(RoundRider.rider_id)
        .with_for_update(read=True, of=User)
        .execution_options(populate_existing=True)
    ).all()
    riders = tuple(
        RiderSnap(rr.rider_id, r.display_name, u.active, rr.vehicle, rr.capacity, rr.start_kind, rr.config_version,
                  rr.route_version, is_confirmed(rr), e.kind if e else None, e.lat if e else None, e.lng if e else None)
        for rr, r, u, e in rider_rows)
    order_rows = db.execute(
        select(Order, Assignment.rider_id)
        .outerjoin(Assignment, Assignment.order_id == Order.id)
        .where(Order.round_id == round_id)
        .order_by(Order.id)
        .execution_options(populate_existing=True)
    ).all()
    orders = tuple(
        OrderSnap(o.id, o.order_code, o.status, o.location_state, o.lat, o.lng, o.locked_rider_id, o.first_priority,
                  owner)
        for o, owner in order_rows)
    return Snapshot(round_id, rnd.input_version, rnd.mode, depots, riders, orders)


def fingerprint(snap: Snapshot, secret: str) -> str:
    """Keyed (HMAC-SHA256) digest of every planning input. Keyed so that low-entropy inputs such
    as a Home location cannot be guessed back from a stored fingerprint. Display names are not
    planning input and are excluded."""
    state = {
        "round": str(snap.round_id), "mode": snap.mode, "depots": snap.depots,
        "riders": [[str(r.rider_id), r.account_active, r.vehicle, r.capacity, r.start_kind, r.config_version,
                    r.confirmed, r.endpoint_kind, r.endpoint_lat, r.endpoint_lng] for r in snap.riders],
        "orders": [[str(o.id), o.status, o.location_state, o.lat, o.lng,
                    str(o.locked_rider_id) if o.locked_rider_id else None, o.first_priority,
                    str(o.owner_rider_id) if o.owner_rider_id else None] for o in snap.orders],
    }
    payload = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), b"routewise-plan-input\0" + payload, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ prechecks and domain


@dataclass
class Prepared:
    domain: DomainRound
    held: dict[uuid.UUID, tuple[uuid.UUID, str]]  # order id -> (owner rider id, "postponed" | "completed")
    pending: list[OrderSnap]
    excluded: dict[str, list[str]]                # completed history not covered by the plan, by reason
    warnings: list[str]
    locations: int


def _names(text: str, names: dict[str, str]) -> str:
    for rid, name in names.items():
        text = text.replace(rid, name)
    return text


def prepare(snap: Snapshot, settings: Settings) -> Prepared:
    """Every check that needs no road data, in the order an admin would fix them. Raises
    PlanningRefused; never changes anything."""
    limits = settings.planning
    names = snap.rider_names()
    order_blockers = readiness_blockers(list(snap.orders), settings.service_area)
    if order_blockers:
        raise PlanningRefused(409, "ORDERS_NOT_READY", "Some orders need a valid pin before planning.",
                              [f"{b['order_code']}: {b['reason']}" for b in order_blockers])
    if not snap.riders:
        raise PlanningRefused(409, "CONFIGURATION_NOT_READY", "Add at least one participating rider.")
    participating = {r.rider_id: r for r in snap.riders}
    not_ready = [r.display_name for r in snap.riders if not (r.confirmed and r.account_active and r.endpoint_kind)]
    if not_ready:
        raise PlanningRefused(409, "CONFIGURATION_NOT_READY",
                              "Every participating rider needs an active account and a current confirmation.", not_ready)

    pending: list[OrderSnap] = []
    held: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    change, postponed_unowned, owner_gone = [], [], []
    excluded: dict[str, list[str]] = {"completed_without_owner": [], "completed_owner_not_participating": []}
    warnings: list[str] = []
    for o in snap.orders:
        if o.status == "Pending":
            pending.append(o)
            continue
        if o.locked_rider_id is not None and o.locked_rider_id != o.owner_rider_id:
            change.append(o.order_code)
        if o.first_priority:
            warnings.append(f"{o.order_code} is {o.status}; its first-delivery flag applies only to Pending orders")
        if o.status == "Postponed":
            if o.owner_rider_id is None:
                postponed_unowned.append(o.order_code)
            elif o.owner_rider_id not in participating:
                owner_gone.append(o.order_code)
            else:
                held[o.id] = (o.owner_rider_id, "postponed")
        else:  # Completed: history only
            if o.owner_rider_id is None:
                excluded["completed_without_owner"].append(o.order_code)
            elif o.owner_rider_id not in participating:
                excluded["completed_owner_not_participating"].append(o.order_code)
            else:
                held[o.id] = (o.owner_rider_id, "completed")
    if change:
        raise PlanningRefused(422, "OWNERSHIP_CHANGE_UNSUPPORTED",
                              "Postponed and Completed orders keep their current rider. Remove the lock that names "
                              "a different rider; handing an order over is not supported.", change)
    if postponed_unowned:
        raise PlanningRefused(422, "POSTPONED_WITHOUT_OWNER",
                              "These Postponed orders have no rider. Set them back to Pending to include them in "
                              "planning.", postponed_unowned)
    if owner_gone:
        raise PlanningRefused(422, "OWNER_NOT_PARTICIPATING",
                              "These Postponed orders belong to a rider who is no longer in this round. Add the rider "
                              "back; reassigning them is not supported.", owner_gone)
    if not pending:
        raise PlanningRefused(422, "NOTHING_TO_PLAN", "There are no Pending orders to plan.")

    held_count: dict[uuid.UUID, int] = {}
    for rider_id, _ in held.values():
        held_count[rider_id] = held_count.get(rider_id, 0) + 1
    over = [f"{r.display_name}: holds {held_count.get(r.rider_id, 0)}, capacity {r.capacity}"
            for r in snap.riders if held_count.get(r.rider_id, 0) > r.capacity]
    if over:
        raise PlanningRefused(422, "HELD_ORDERS_EXCEED_CAPACITY",
                              "A rider's Postponed and Completed orders already exceed their capacity. Raise it.", over)

    # Distinct road points: orders, both starts in use and fixed destinations.
    domain, loc_count = _domain(snap, pending, held_count)
    if (len(pending) > limits.max_pending_orders or len(snap.riders) > limits.max_riders
            or loc_count > limits.max_locations):
        raise PlanningRefused(422, "ROUND_TOO_LARGE",
                              f"This round has {len(pending)} Pending orders, {len(snap.riders)} riders and "
                              f"{loc_count} road points. The local limits are {limits.max_pending_orders} orders, "
                              f"{limits.max_riders} riders and {limits.max_locations} points per run.")
    try:
        planner._precheck(domain)
        stops = planner.build_stops(domain, [o.id for o in domain.orders], max(r.capacity for r in domain.riders) or 1)
        planner._priority_check(stops, len(domain.riders))
    except planner.PlanningError as exc:
        raise PlanningRefused(409 if exc.code == "ENDPOINTS_NOT_CONFIRMED" else 422, exc.code,
                              _names(exc.message, names), [_names(d, names) for d in exc.details]) from None
    return Prepared(domain, held, pending, excluded, warnings, loc_count)


def _domain(snap: Snapshot, pending: list[OrderSnap], held_count: dict[uuid.UUID, int]) -> tuple[DomainRound, int]:
    """In-memory planner input. Location ids are opaque (L0, L1, ...); identical coordinates
    share one road point. Capacity left for planning = capacity - orders already held."""
    points: dict[tuple[float, float], str] = {}
    locations: dict[str, Location] = {}

    def loc(lat: float, lng: float) -> str:
        key = (lat, lng)
        if key not in points:
            points[key] = f"L{len(points)}"
            locations[points[key]] = Location(points[key], "", lat, lng)
        return points[key]

    depot_ids = {kind: f"depot:{kind}" for kind in ("office", "warehouse")}
    depot_coords = {kind: (lat, lng) for kind, lat, lng in snap.depots}
    used_depots = {r.start_kind for r in snap.riders} | {r.endpoint_kind for r in snap.riders
                                                         if r.endpoint_kind in ("office", "warehouse")}
    for kind in sorted(used_depots):
        if kind in depot_coords:
            depot_ids[kind] = loc(*depot_coords[kind])
    riders = []
    for r in snap.riders:
        end_loc = None
        if r.endpoint_kind in ("home", "custom") and r.endpoint_lat is not None:
            end_loc = loc(r.endpoint_lat, r.endpoint_lng)
        elif r.endpoint_kind in ("office", "warehouse"):
            end_loc = depot_ids[r.endpoint_kind]
        riders.append(DomainRider(
            id=str(r.rider_id), vehicle=Vehicle(r.vehicle), capacity=r.capacity - held_count.get(r.rider_id, 0),
            start=StartKind(r.start_kind),
            endpoint=Endpoint(EndpointKind(r.endpoint_kind), end_loc if r.endpoint_kind in ("home", "custom") else None,
                              r.confirmed)))
    orders = [DomainOrder(id=o.order_code, location_id=loc(o.lat, o.lng),
                          locked_rider_id=str(o.locked_rider_id) if o.locked_rider_id else None,
                          first_priority=o.first_priority) for o in pending]
    domain = DomainRound(id=str(snap.round_id), depots=Depots(depot_ids["office"], depot_ids["warehouse"]),
                         riders=riders, orders=orders, locations=locations, mode=DistributionMode(snap.mode))
    return domain, len(points)


# ------------------------------------------------------------------ solving (no database)


class _TimedProvider:
    def __init__(self, inner):
        self.inner, self.name, self.seconds, self.calls = inner, getattr(inner, "name", "provider"), 0.0, 0

    def compute(self, origins, destinations, profile) -> RoadMatrix:
        t0 = time.monotonic()
        try:
            return self.inner.compute(origins, destinations, profile)
        finally:
            self.seconds += time.monotonic() - t0
            self.calls += 1


_EQUAL_MISS = re.compile(r"^equal target (\d+)-(\d+) not met for (.+?) \((\d+)\) due to locks/grouping$")


def _explain_equal(warning: str, domain: DomainRound) -> str:
    """The spike always blamed locks/grouping; say what actually prevented an equal split."""
    m = _EQUAL_MISS.match(warning)
    if not m:
        return warning
    lo, hi, rid, got = int(m[1]), int(m[2]), m[3], int(m[4])
    locked = sum(1 for o in domain.orders if o.locked_rider_id == rid)
    head = f"Equal target {lo}–{hi} orders not met for {rid}: {got} orders"
    if locked > hi:
        return f"{head}, because {locked} orders are locked to this rider."
    return (f"{head}. Locks and capacities allow an equal split, but the time-bounded search did not reach it; "
            "optimizing again or adjusting locks may help.")


@dataclass
class Solved:
    plan: planner.Plan
    timings: dict = field(default_factory=dict)


def solve(prepared: Prepared, provider, limits: PlanningLimits) -> Solved:
    timed = _TimedProvider(provider)
    t0 = time.monotonic()
    plan = planner.optimize_round(prepared.domain, timed, profile=DOMAIN_PROFILE, metric="distance",
                                  time_limit_s=limits.solve_seconds)
    total = time.monotonic() - t0
    plan.warnings = [_explain_equal(w, prepared.domain) for w in plan.warnings]
    if not plan.provenance.get("real_road"):
        raise planner.PlanningError("NOT_ROAD_DISTANCES",
                                    "The matrix is not real road data; a plan is never saved from it.")
    return Solved(plan, {"matrix_s": round(timed.seconds, 3), "solve_s": round(total - timed.seconds, 3),
                         "total_s": round(total, 3), "matrix_calls": timed.calls, "points": prepared.locations,
                         "pending_orders": len(prepared.pending), "riders": len(prepared.domain.riders)})


# ------------------------------------------------------------------ commit


def _finish(run: PlanningRun, state: str, now: datetime, code: str | None = None, message: str | None = None,
            details: list | None = None) -> None:
    run.state, run.finished_at = state, now
    run.error_code, run.error_message, run.error_details = code, (message or None) and message[:500], details


def commit_plan(db: DBSession, run_id: uuid.UUID, snap: Snapshot, prepared: Prepared, solved: Solved,
                secret: str, now: datetime, before_write=None) -> str:
    """Save the plan atomically if, under lock, the input is still exactly the snapshot's.
    Returns the run's final state. The caller commits or rolls back `db`. `before_write`
    (tests only) is called after the final check and before any plan or assignment write."""
    lock_depots_shared(db)
    rnd = lock_round(db, snap.round_id)
    run = db.get(PlanningRun, run_id, with_for_update=True, populate_existing=True)
    if rnd is None or run is None or run.state != "running":
        return run.state if run is not None else "missing"
    run.timings = solved.timings
    fresh = capture(db, snap.round_id)
    if rnd.input_version != run.input_version or fingerprint(fresh, secret) != run.input_fingerprint:
        _finish(run, "stale", now, "INPUTS_CHANGED",
                "The round changed while this plan was being computed. Nothing was saved; optimize again.")
        return "stale"
    if before_write is not None:
        before_write(run_id)

    plan = solved.plan
    names = snap.rider_names()
    by_code = {o.order_code: o for o in snap.orders}
    riders = {str(r.rider_id): r for r in snap.riders}
    previous = db.scalar(select(RoutePlan).where(RoutePlan.round_id == snap.round_id, RoutePlan.is_current.is_(True))
                         .with_for_update())
    version = (db.scalar(select(func.max(RoutePlan.version)).where(RoutePlan.round_id == snap.round_id)) or 0) + 1
    superseded_revisions: list[str] = []
    if previous is not None:
        previous.is_current, previous.superseded_at = False, now
        # 4B: riders' own recalculated routes belong to the plan being replaced; they are kept as
        # history, marked superseded, and are never effective for the new plan.
        superseded_revisions = sorted({str(rid) for rid in db.scalars(
            update(RouteRevision).where(RouteRevision.plan_id == previous.id, RouteRevision.is_current.is_(True))
            .values(is_current=False, superseded_at=now).returning(RouteRevision.rider_id)).all()})
        db.flush()  # the partial unique index allows one current plan; clear the old one first

    planned = {by_code[code].id: uuid.UUID(rid) for code, rid in plan.assignments.items()}
    changes = [{"order_code": o.order_code, "from_rider_id": str(o.owner_rider_id), "to_rider_id": str(planned[o.id])}
               for o in prepared.pending if o.owner_rider_id is not None and o.owner_rider_id != planned[o.id]]
    summary = {
        "planned_orders": len(planned),
        "postponed_held": sum(1 for _, role in prepared.held.values() if role == "postponed"),
        "completed_held": sum(1 for _, role in prepared.held.values() if role == "completed"),
        **prepared.excluded,
        "ownership_changes": changes,
        "rider_revisions_superseded": superseded_revisions,  # rider ids whose own recalculated route this plan replaces
        "total_road_distance_m": sum(r.road_distance_m for r in plan.routes.values()),
        "total_road_duration_s": sum(r.road_duration_s for r in plan.routes.values()),
    }
    provenance = dict(plan.provenance)
    provenance["profiles_by_vehicle"] = VEHICLE_PROFILE
    row = RoutePlan(round_id=snap.round_id, version=version, run_id=run.id, is_current=True, mode=snap.mode,
                    input_version=run.input_version, input_fingerprint=run.input_fingerprint,
                    # Read under the round lock after the final check: no input change (and so no
                    # route_version change) has committed since the snapshot.
                    route_version=rnd.route_version,
                    distance_label=plan.distance_label[:300], provenance=provenance,
                    warnings=[_names(w, names) for w in [*plan.warnings, *prepared.warnings]],
                    summary=summary, created_by=run.requested_by, created_at=now)
    db.add(row)
    db.flush()
    for rid, route in plan.routes.items():
        r = riders[rid]
        db.add(PlanRoute(plan_id=row.id, rider_id=r.rider_id, vehicle=r.vehicle, profile=VEHICLE_PROFILE[r.vehicle],
                         capacity=r.capacity, start_kind=r.start_kind, endpoint_kind=r.endpoint_kind,
                         open_route=route.end_location_id is None, road_distance_m=route.road_distance_m,
                         road_duration_s=route.road_duration_s, rider_route_version=r.route_version))
    db.flush()
    for rid, route in plan.routes.items():
        for seq, stop in enumerate(route.stops, start=1):
            for code in stop.order_ids:
                db.add(PlanOrder(plan_id=row.id, order_id=by_code[code].id, rider_id=uuid.UUID(rid), role="active",
                                 stop_seq=seq))
    for order_id, (owner, role) in prepared.held.items():
        db.add(PlanOrder(plan_id=row.id, order_id=order_id, rider_id=owner, role=role, stop_seq=None))
    db.flush()

    # Ownership: Pending orders get their planned rider; held orders keep theirs (only the link moves).
    for order_id, rider_id in planned.items():
        stmt = pg_insert(Assignment).values(order_id=order_id, rider_id=rider_id, plan_id=row.id, assigned_at=now)
        db.execute(stmt.on_conflict_do_update(index_elements=["order_id"], set_={
            "rider_id": stmt.excluded.rider_id, "plan_id": stmt.excluded.plan_id,
            # keep the original time when the rider is unchanged
            "assigned_at": case((Assignment.rider_id == stmt.excluded.rider_id, Assignment.assigned_at),
                                else_=stmt.excluded.assigned_at)}))
    held_ids = list(prepared.held)
    if held_ids:
        db.execute(update(Assignment).where(Assignment.order_id.in_(held_ids)).values(plan_id=row.id))
    db.flush()

    # Independent re-read before the transaction can commit.
    rows = db.execute(select(PlanOrder.order_id, PlanOrder.rider_id, PlanOrder.role)
                      .where(PlanOrder.plan_id == row.id)).all()
    expected = {**{k: (v, "active") for k, v in planned.items()}, **prepared.held}
    if {o: (r, role) for o, r, role in rows} != expected:
        raise RuntimeError("persisted plan disagrees with the solver output")
    owners = dict(db.execute(select(Assignment.order_id, Assignment.rider_id)
                             .where(Assignment.order_id.in_(list(expected)))).all())
    if owners != {o: r for o, (r, _) in expected.items()}:
        raise RuntimeError("assignments disagree with the plan")
    if any(o.status == "Completed" and o.owner_rider_id is not None and owners.get(o.id, o.owner_rider_id)
           != o.owner_rider_id for o in snap.orders):
        raise RuntimeError("completed history changed")
    _finish(run, "succeeded", now)
    return "succeeded"


def plan_validity(plan: RoutePlan, rnd: DeliveryRound) -> dict:
    """3B. `out_of_date`: the saved routes are no longer usable (any planning-input change other
    than a rider's own delivery progress since the plan). `progress_since_plan`: only riders'
    delivery progress has happened since; the remaining saved sequence is still valid."""
    out_of_date = plan.route_version != rnd.route_version
    return {"out_of_date": out_of_date,
            "progress_since_plan": not out_of_date and plan.input_version != rnd.input_version}


# ------------------------------------------------------------------ worker


@dataclass
class _Job:
    run_id: uuid.UUID
    snap: object       # Snapshot, or reroute.RiderSnapshot for a rider run
    prepared: object   # Prepared, or reroute.RiderPrepared
    runner: object = None  # callable(job) for rider runs; None = round run (`PlanningService.run`)


class PlanningService:
    """Bounded in-process planning: `workers` threads, at most `workers + queue_size` runs
    accepted at once (a slot is reserved before a run row is created)."""

    def __init__(self, settings: Settings, session_factory, clock):
        self.settings, self.session_factory, self.clock = settings, session_factory, clock
        self.limits = settings.planning
        self.provider_override = None  # tests inject recorded matrices here; never set from configuration
        self.hooks: dict = {}          # tests only: "after_solve"(run_id) pauses between solve and commit,
        #                                "before_write"(run_id) after the commit's final check, locks held
        self._provider = None
        self._provider_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(self.limits.workers + self.limits.queue_size)
        self._queue: queue.Queue = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._start_lock = threading.Lock()

    def provider(self):
        if self.provider_override is not None:
            return self.provider_override
        with self._provider_lock:
            if self._provider is None:
                self._provider = ValhallaLocalProvider(
                    self.settings.valhalla_tiles, max_locations=self.limits.max_locations,
                    data_note="Local tiles built by spikes/valhalla/build_tiles.sh (DU North Campus buffer).")
            return self._provider

    def try_reserve(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release(self) -> None:
        self._slots.release()

    def submit(self, run_id: uuid.UUID, snap: Snapshot, prepared: Prepared, runner=None) -> None:
        with self._start_lock:
            while len(self._threads) < self.limits.workers:
                t = threading.Thread(target=self._loop, name=f"routewise-planning-{len(self._threads)}", daemon=True)
                t.start()
                self._threads.append(t)
        self._queue.put(_Job(run_id, snap, prepared, runner))

    def shutdown(self, timeout: float = 30) -> None:
        for _ in self._threads:
            self._queue.put(None)
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                (job.runner or self.run)(job)
            except Exception:  # never let a worker thread die; the run is marked failed in run()
                log.exception("planning worker error (run %s)", job.run_id)
            finally:
                self.release()

    def _set(self, run_id: uuid.UUID, state: str, *, expect: tuple[str, ...], **error) -> bool:
        with self.session_factory() as db:
            run = db.get(PlanningRun, run_id, with_for_update=True)
            if run is None or run.state not in expect:
                db.rollback()
                return False
            if state == "running":
                run.state, run.started_at = "running", self.clock()
            else:
                _finish(run, state, self.clock(), **error)
            db.commit()
            return True

    def run(self, job: _Job) -> None:
        if not self._set(job.run_id, "running", expect=("queued",)):
            return  # interrupted or removed meanwhile
        try:
            solved = solve(job.prepared, self.provider(), self.limits)
        except planner.PlanningError as exc:
            names = job.snap.rider_names()
            log.info("planning run %s failed: %s", job.run_id, exc.code)
            self._set(job.run_id, "failed", expect=("running",), code=exc.code, message=_names(exc.message, names),
                      details=[_names(d, names) for d in exc.details])
            return
        except ProviderError as exc:
            log.warning("planning run %s: routing engine unavailable (%s)", job.run_id, type(exc).__name__)
            self._set(job.run_id, "failed", expect=("running",), code="ROUTING_ENGINE_UNAVAILABLE",
                      message="The local road-routing engine failed. No plan was saved; the previous plan is unchanged.")
            return
        except Exception as exc:
            log.error("planning run %s: unexpected %s", job.run_id, type(exc).__name__)
            self._set(job.run_id, "failed", expect=("running",), code="INTERNAL",
                      message="Planning failed unexpectedly. No plan was saved; the previous plan is unchanged.")
            return
        hook = self.hooks.get("after_solve")
        if hook:
            hook(job.run_id)
        try:
            with self.session_factory() as db:
                state = commit_plan(db, job.run_id, job.snap, job.prepared, solved, self.settings.secret_key,
                                    self.clock(), before_write=self.hooks.get("before_write"))
                db.commit()
            log.info("planning run %s: %s", job.run_id, state)
        except Exception as exc:
            log.error("planning run %s: commit failed (%s)", job.run_id, type(exc).__name__)
            self._set(job.run_id, "failed", expect=("running",), code="INTERNAL",
                      message="Saving the plan failed. Nothing was saved; the previous plan is unchanged.")


def recover_interrupted_runs(session_factory, now: datetime) -> int:
    """On start-up: queued/running runs belong to a process that is gone (snapshots live only in
    memory). They are marked `interrupted`, never successful. Assumes one API process per
    database, as for the Phase 1 import limit."""
    with session_factory() as db:
        n = db.execute(update(PlanningRun).where(PlanningRun.state.in_(ACTIVE_RUN_STATES)).values(
            state="interrupted", finished_at=now, error_code="INTERRUPTED",
            error_message="The API stopped before this run finished. Nothing was saved; optimize again.")).rowcount
        db.commit()
    if n:
        log.warning("marked %d unfinished planning run(s) as interrupted", n)
    return n


def expire_overdue(db: DBSession, run: PlanningRun, now: datetime, limit_s: int) -> None:
    """A run queued or running far beyond every bound is reported as interrupted (its worker is
    gone). Called while reading a run; never marks unfinished work as successful."""
    if run.state in ACTIVE_RUN_STATES and (now - run.requested_at).total_seconds() > limit_s:
        locked = db.get(PlanningRun, run.id, with_for_update=True, populate_existing=True)
        if locked.state in ACTIVE_RUN_STATES:
            _finish(locked, "interrupted", now, "INTERRUPTED",
                    "This run did not finish within its time bound. Nothing was saved; optimize again.")


__all__ = ["PlanningRefused", "PlanningService", "Snapshot", "capture", "commit_plan", "fingerprint", "prepare",
           "recover_interrupted_runs", "expire_overdue", "solve"]
