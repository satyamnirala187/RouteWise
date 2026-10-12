"""Initial multi-rider optimization on top of OR-Tools.

Contract (docs/source/notion/RouteWise/03-Architecture.md, "Routing contract"):
- endpoint confirmation gate first; unresolved locations block planning
- per-rider start and fixed end; Last stop = zero-cost virtual sink that is never
  reported as driving distance
- capacity counted in orders; grouped stops keep their underlying order demand
- manual locks, equal-count targets, first-delivery priority (D05)
- missing road edges are forbidden arcs, never zero; nothing is silently dropped
- bounded solve; feasible result, not a proven optimum
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .gate import endpoint_gate_issues
from .matrix.base import MatrixProvider, RoadMatrix
from .models import (
    DeliveryRound,
    DistributionMode,
    EndpointKind,
    OrderStatus,
    Plan,
    RiderRoute,
    Stop,
)

FORBIDDEN = 10**9
EQUAL_PENALTY = 10_000_000  # per order away from the equal-count band; dominates metres
SOLVER_STATUS = {0: "NOT_SOLVED", 1: "SUCCESS", 2: "PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED", 3: "FAIL",
                 4: "FAIL_TIMEOUT", 5: "INVALID", 6: "INFEASIBLE", 7: "OPTIMAL"}


class PlanningError(Exception):
    def __init__(self, code: str, message: str, details: list[str] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or []


class StalePlanError(Exception):
    pass


@dataclass
class VehicleSpec:
    rider_id: str
    capacity: int
    start_location_id: str
    end_location_id: str | None  # None => open route (Last stop)


@dataclass
class StopSpec:
    location_id: str
    order_ids: list[str]
    building_id: str | None = None
    locked_rider_id: str | None = None
    priority: bool = False

    @property
    def demand(self) -> int:
        return len(self.order_ids)


@dataclass
class SolveResult:
    sequences: dict[str, list[StopSpec]]
    objective: int
    strategy: str
    status: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- grouping


def build_stops(rnd: DeliveryRound, order_ids: list[str], max_capacity: int) -> list[StopSpec]:
    """Group orders sharing a validated building id (and the same manual owner).

    Proximity alone never groups. A manually split building stays split.
    """
    groups: dict[tuple, list] = {}
    for oid in order_ids:
        o = rnd.order(oid)
        key = ("b", o.building_id, o.location_id, o.locked_rider_id) if o.building_id else ("o", o.id)
        groups.setdefault(key, []).append(o)
    stops: list[StopSpec] = []
    for orders in groups.values():
        cap = max_capacity
        if orders[0].locked_rider_id:
            cap = rnd.rider(orders[0].locked_rider_id).capacity
        cap = max(cap, 1)
        for i in range(0, len(orders), cap):  # a building larger than any rider is split
            chunk = orders[i : i + cap]
            stops.append(
                StopSpec(
                    location_id=chunk[0].location_id,
                    order_ids=[o.id for o in chunk],
                    building_id=chunk[0].building_id,
                    locked_rider_id=chunk[0].locked_rider_id,
                    priority=any(o.first_priority for o in chunk),
                )
            )
    return stops


def equal_bounds(total: int, capacities: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Near-equal order-count band per rider, respecting capacity (water filling)."""
    if total == 0:
        return {r: (0, 0) for r in capacities}
    level = 0
    while sum(min(c, level) for c in capacities.values()) < total:
        level += 1
    return {r: (min(c, level - 1), min(c, level)) for r, c in capacities.items()}


# ---------------------------------------------------------------- solving


def solve(
    vehicles: list[VehicleSpec],
    stops: list[StopSpec],
    matrix: RoadMatrix,
    *,
    metric: str = "distance",
    bounds: dict[str, tuple[int, int]] | None = None,
    time_limit_s: int = 10,
    solution_limit: int = 1000,
) -> SolveResult:
    n_stops = len(stops)
    v_index = {v.rider_id: i for i, v in enumerate(vehicles)}
    # Node layout: stops, then (start, end) per vehicle.
    node_loc: list[str | None] = [s.location_id for s in stops]
    starts, ends = [], []
    for v in vehicles:
        starts.append(len(node_loc))
        node_loc.append(v.start_location_id)
        ends.append(len(node_loc))
        node_loc.append(v.end_location_id)  # None = virtual sink
    n = len(node_loc)

    cost = [[0] * n for _ in range(n)]
    allowed = [[True] * n for _ in range(n)]
    for a in range(n):
        for b in range(n):
            if a == b:
                continue
            la, lb = node_loc[a], node_loc[b]
            if lb is None:  # into a Last-stop virtual sink: free, not driving distance
                cost[a][b] = 0
            elif la is None:
                cost[a][b] = FORBIDDEN
                allowed[a][b] = False
            else:
                c = matrix.cost(la, lb, metric)
                if c is None:
                    cost[a][b] = FORBIDDEN
                    allowed[a][b] = False
                else:
                    cost[a][b] = c

    manager = pywrapcp.RoutingIndexManager(n, len(vehicles), starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    def arc(i: int, j: int) -> int:
        return cost[manager.IndexToNode(i)][manager.IndexToNode(j)]

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(arc))

    def index_of(node: int) -> int:
        if node < n_stops:
            return manager.NodeToIndex(node)
        k, is_end = divmod(node - n_stops, 2)
        return routing.End(k) if is_end else routing.Start(k)

    for a in range(n):
        if a >= n_stops and (a - n_stops) % 2 == 1:
            continue  # end nodes have no NextVar
        ia = index_of(a)
        for b in range(n):
            if a != b and not allowed[a][b]:
                routing.NextVar(ia).RemoveValue(index_of(b))

    demand = [s.demand for s in stops] + [0] * (2 * len(vehicles))
    d_cb = routing.RegisterUnaryTransitCallback(lambda i: demand[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(d_cb, 0, [v.capacity for v in vehicles], True, "Orders")
    orders_dim = routing.GetDimensionOrDie("Orders")
    for i, s in enumerate(stops):
        idx = manager.NodeToIndex(i)
        if s.locked_rider_id is not None:
            # OR-Tools 9.15's SetAllowedVehiclesForIndex binding rejects Python lists.
            routing.VehicleVar(idx).SetValues([v_index[s.locked_rider_id]])
        if s.priority:
            # First delivery (D05): only a route start may precede a priority stop.
            # A domain restriction propagates far better than a position side-constraint,
            # and two priority stops can never share a route.
            for j in range(n_stops):
                if j != i:
                    routing.NextVar(manager.NodeToIndex(j)).RemoveValue(idx)

    if bounds:
        for v in vehicles:
            lo, hi = bounds[v.rider_id]
            end = routing.End(v_index[v.rider_id])
            orders_dim.SetCumulVarSoftUpperBound(end, hi, EQUAL_PENALTY)
            orders_dim.SetCumulVarSoftLowerBound(end, lo, EQUAL_PENALTY)

    # Insertion first: cheapest-arc construction closes Last-stop routes immediately
    # (the virtual sink costs 0) and then backtracks for minutes on locks/priorities.
    strategies = [
        routing_enums_pb2.FirstSolutionStrategy.LOCAL_CHEAPEST_INSERTION,
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
    ]
    solution, used = None, ""
    for strat in strategies:
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = strat
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        # A solution-count bound keeps runs reproducible across machines; the
        # wall-clock limit is only a safety net and is reported when it triggers.
        params.solution_limit = solution_limit
        params.time_limit.FromSeconds(time_limit_s)
        solution = routing.SolveWithParameters(params)
        if solution is not None:
            used = routing_enums_pb2.FirstSolutionStrategy.Value.Name(strat)
            break
    if solution is None:
        raise PlanningError(
            "NO_FEASIBLE_PLAN",
            "No plan satisfies capacities, locks, priorities and reachable road edges "
            f"within {time_limit_s}s per strategy. No order was dropped.",
            _reachability_hints(stops, vehicles, matrix),
        )
    status = SOLVER_STATUS.get(routing.status(), str(routing.status()))
    warnings = []
    if status != "SUCCESS":
        warnings.append(f"solver status {status}: time limit reached before the solution limit; result may vary by machine")

    sequences: dict[str, list[StopSpec]] = {}
    for k, v in enumerate(vehicles):
        seq, idx = [], routing.Start(k)
        while True:
            idx = solution.Value(routing.NextVar(idx))
            if routing.IsEnd(idx):
                break
            seq.append(stops[manager.IndexToNode(idx)])
        sequences[v.rider_id] = seq
    return SolveResult(sequences, solution.ObjectiveValue(), used, status, warnings)


def _reachability_hints(stops, vehicles, matrix: RoadMatrix) -> list[str]:
    hints = []
    starts = {v.start_location_id for v in vehicles}
    for s in stops:
        incoming = [x for x in starts | {t.location_id for t in stops} if x != s.location_id]
        if all(matrix.cost(x, s.location_id) is None for x in incoming):
            hints.append(f"stop with orders {s.order_ids} cannot be reached by road from any start or stop")
    return hints


# ---------------------------------------------------------------- route assembly


def route_cost(matrix: RoadMatrix, path: list[str]) -> tuple[int, int]:
    dist = dur = 0
    for a, b in zip(path, path[1:]):
        el = matrix.get(a, b)
        if el.distance_m is None:
            raise PlanningError("INTERNAL", f"route uses a missing road edge {a}->{b}")
        dist += el.distance_m
        dur += el.duration_s
    return dist, dur


def merge_building_stops(seq: list[StopSpec]) -> list[Stop]:
    """Consecutive stops at the same validated building become one navigation stop."""
    out: list[Stop] = []
    for s in seq:
        if out and s.building_id and out[-1].building_id == s.building_id and out[-1].location_id == s.location_id:
            out[-1].order_ids.extend(s.order_ids)
        else:
            out.append(Stop(s.location_id, list(s.order_ids), s.building_id))
    return out


def assemble_route(
    rider_id: str, version: int, vehicle: VehicleSpec, endpoint_kind: EndpointKind, seq: list[StopSpec], matrix: RoadMatrix
) -> RiderRoute:
    stops = merge_building_stops(seq)
    path = [vehicle.start_location_id] + [s.location_id for s in stops]
    if vehicle.end_location_id is not None:
        path.append(vehicle.end_location_id)
    dist, dur = route_cost(matrix, path)
    return RiderRoute(
        rider_id=rider_id,
        version=version,
        start_location_id=vehicle.start_location_id,
        endpoint_kind=endpoint_kind,
        end_location_id=vehicle.end_location_id,
        stops=stops,
        road_distance_m=dist,
        road_duration_s=dur,
    )


# ---------------------------------------------------------------- initial plan


def fingerprint(rnd: DeliveryRound) -> str:
    state = {
        "mode": rnd.mode.value,
        "depots": [rnd.depots.office_location_id, rnd.depots.warehouse_location_id],
        "riders": [
            [r.id, r.vehicle.value, r.capacity, r.start.value, r.active]
            + ([r.endpoint.kind.value, r.endpoint.location_id, r.endpoint.confirmed] if r.endpoint else [None])
            for r in rnd.riders
        ],
        "orders": [
            [o.id, o.location_id, o.building_id, o.status.value, o.locked_rider_id, o.first_priority]
            for o in rnd.orders
        ],
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:16]


def _precheck(rnd: DeliveryRound) -> None:
    gate = endpoint_gate_issues(rnd)
    if gate:
        raise PlanningError(
            "ENDPOINTS_NOT_CONFIRMED",
            "Initial optimization waits until every active rider confirms a valid endpoint.",
            [f"{g.rider_id}: {g.reason}" for g in gate],
        )
    riders = rnd.active_riders()
    if not riders:
        raise PlanningError("NO_ACTIVE_RIDERS", "No active riders in this round.")
    for depot in (rnd.depots.office_location_id, rnd.depots.warehouse_location_id):
        if depot not in rnd.locations:
            raise PlanningError("UNRESOLVED_LOCATION", "Office/Warehouse location is not resolved.")
    unresolved = [o.id for o in rnd.orders if o.location_id is None or o.location_id not in rnd.locations]
    if unresolved:
        raise PlanningError("UNRESOLVED_LOCATION", "Orders need a confirmed pin before planning.", unresolved)
    not_pending = [o.id for o in rnd.orders if o.status is not OrderStatus.PENDING]
    if not_pending:
        raise PlanningError("INITIAL_STATUS", "Initial optimization expects freshly imported Pending orders.", not_pending)
    active_ids = {r.id for r in riders}
    bad_locks = [o.id for o in rnd.orders if o.locked_rider_id and o.locked_rider_id not in active_ids]
    if bad_locks:
        raise PlanningError("INVALID_LOCK", "Orders are locked to a rider who is not active in this round.", bad_locks)
    if rnd.mode is DistributionMode.MANUAL:
        missing = [o.id for o in rnd.orders if not o.locked_rider_id]
        if missing:
            raise PlanningError("MANUAL_ASSIGNMENT_MISSING", "Manual mode needs an admin-chosen rider for every order.", missing)
    total_cap = sum(r.capacity for r in riders)
    if len(rnd.orders) > total_cap:
        raise PlanningError(
            "INSUFFICIENT_CAPACITY",
            f"{len(rnd.orders)} orders exceed total rider capacity {total_cap}. Add a rider or raise a capacity; no order is dropped.",
        )
    for r in riders:
        locked = sum(1 for o in rnd.orders if o.locked_rider_id == r.id)
        if locked > r.capacity:
            raise PlanningError("LOCK_EXCEEDS_CAPACITY", f"{locked} orders locked to {r.id} exceed capacity {r.capacity}.", [r.id])


def _priority_check(stops: list[StopSpec], n_riders: int) -> None:
    prio = [s for s in stops if s.priority]
    details = []
    per_rider: dict[str, list[StopSpec]] = {}
    for s in prio:
        if s.locked_rider_id:
            per_rider.setdefault(s.locked_rider_id, []).append(s)
    for rid, ss in per_rider.items():
        if len(ss) > 1:
            details.append(f"{rid} has {len(ss)} first-priority stops: {[s.order_ids for s in ss]}")
    if len(prio) > n_riders:
        details.append(f"{len(prio)} first-priority stops but only {n_riders} riders can each start with one")
    if details:
        raise PlanningError("PRIORITY_CONFLICT", "Each rider route can have only one first delivery (D05).", details)


def optimize_round(
    rnd: DeliveryRound,
    provider: MatrixProvider,
    *,
    profile: str,
    metric: str = "distance",
    time_limit_s: int = 30,  # ~14 s measured at 100 orders / 8 riders (solver_benchmark.md)
    plan_version: int = 1,
) -> Plan:
    _precheck(rnd)
    riders = rnd.active_riders()
    vehicles = [
        VehicleSpec(r.id, r.capacity, rnd.start_location_id(r), rnd.end_location_id(r.endpoint)) for r in riders
    ]
    stops = build_stops(rnd, [o.id for o in rnd.orders], max(r.capacity for r in riders))
    _priority_check(stops, len(riders))

    loc_ids = sorted({s.location_id for s in stops} | {v.start_location_id for v in vehicles}
                     | {v.end_location_id for v in vehicles if v.end_location_id})
    locs = [rnd.locations[i] for i in loc_ids]
    matrix = provider.compute(locs, locs, profile)

    bounds = None
    if rnd.mode is DistributionMode.EQUAL:
        bounds = equal_bounds(len(rnd.orders), {r.id: r.capacity for r in riders})
    result = solve(vehicles, stops, matrix, metric=metric, bounds=bounds, time_limit_s=time_limit_s)

    routes = {}
    for v, r in zip(vehicles, riders):
        routes[r.id] = assemble_route(r.id, 1, v, r.endpoint.kind, result.sequences[r.id], matrix)
    assignments = {oid: rid for rid, route in routes.items() for oid in route.order_ids()}
    warnings = list(result.warnings)
    if bounds:
        for rid, route in routes.items():
            lo, hi = bounds[rid]
            if not lo <= len(route.order_ids()) <= hi:
                warnings.append(f"equal target {lo}-{hi} not met for {rid} ({len(route.order_ids())}) due to locks/grouping")
    plan = Plan(
        round_id=rnd.id,
        version=plan_version,
        input_fingerprint=fingerprint(rnd),
        mode=rnd.mode,
        routes=routes,
        assignments=assignments,
        distance_label=matrix.provenance.label(),
        provenance=matrix.provenance.as_dict() | {"solver_strategy": result.strategy, "solver_status": result.status, "objective": result.objective, "metric": metric},
        warnings=warnings,
    )
    violations = validate_plan(rnd, plan)
    if violations:
        raise PlanningError("INTERNAL", "Solver output violated a constraint.", violations)
    return plan


def validate_plan(rnd: DeliveryRound, plan: Plan) -> list[str]:
    """Independent invariant check, used by the planner and by tests."""
    v: list[str] = []
    seen: dict[str, str] = {}
    for rid, route in plan.routes.items():
        rider = rnd.rider(rid)
        for oid in route.order_ids() + route.postponed_order_ids + route.completed_order_ids:
            if oid in seen:
                v.append(f"{oid} owned by {seen[oid]} and {rid}")
            seen[oid] = rid
        if len(route.order_ids()) + len(route.postponed_order_ids) + len(route.completed_order_ids) > rider.capacity:
            v.append(f"{rid} exceeds capacity {rider.capacity}")
        if route.origin_kind == "configured_start" and route.start_location_id != rnd.start_location_id(rider):
            v.append(f"{rid} does not start at configured start")
        if route.end_location_id != rnd.end_location_id(rider.endpoint):
            v.append(f"{rid} does not end at the confirmed endpoint")
        for oid in route.order_ids():
            o = rnd.order(oid)
            if o.locked_rider_id and o.locked_rider_id != rid:
                v.append(f"{oid} is locked to {o.locked_rider_id} but planned for {rid}")
        prio = [i for i, s in enumerate(route.stops) if any(rnd.order(o).first_priority for o in s.order_ids)]
        if prio and prio != [0]:
            v.append(f"{rid} first-priority stop is not the first active delivery")
    missing = {o.id for o in rnd.orders} - set(seen)
    if missing:
        v.append(f"orders without owner: {sorted(missing)}")
    if plan.assignments != seen:
        v.append("assignment table disagrees with routes")
    return v


class PlanStore:
    """Atomic, versioned plan commits: stale output cannot overwrite newer state."""

    def __init__(self):
        self.current: dict[str, Plan] = {}

    def commit(self, rnd: DeliveryRound, plan: Plan) -> Plan:
        if plan.input_fingerprint != fingerprint(rnd):
            raise StalePlanError("round changed while the plan was being computed; recompute")
        cur = self.current.get(rnd.id)
        if cur is not None and plan.version <= cur.version:
            raise StalePlanError(f"plan version {plan.version} is not newer than {cur.version}")
        self.current[rnd.id] = plan
        return plan
