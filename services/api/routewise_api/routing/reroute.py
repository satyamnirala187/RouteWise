"""Rider-only re-sequence (step 4B), in memory; no database.

Ported from spikes/routing/routewise_spike/reroute.py (accepted Phase 0, `reroute_rider`) and
adapted to the application:
- The caller (routewise_api/reroute.py) has already chosen the origin explicitly; this module
  never picks one. The spike's `choose_origin` rule (fresh position first; otherwise the last
  completed stop, labelled; otherwise ask the rider) lives in the caller as explicit requests.
- Only the given orders (the rider's own Pending orders) are sequenced; ownership is not an
  input here and cannot change. The spike returned a whole new round plan; the application keeps
  the round plan immutable and stores the result as a rider route revision.
- The vehicle starts at the origin and ends at the rider's confirmed endpoint, or at the last
  delivery for Last stop (open route; the virtual final arc is never counted).
- Provider failures propagate (`ProviderError`); the caller keeps the last valid route.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import DeliveryRound, Depots, Endpoint, EndpointKind, Location, Order, Rider, RiderRoute, StartKind, Vehicle
from .matrix.base import Provenance
from .planner import (
    PlanningError,
    SolveResult,
    VehicleSpec,
    _endpoint_check,
    _priority_check,
    _unroutable_check,
    assemble_route,
    build_stops,
    solve,
)


@dataclass(frozen=True)
class RerouteInput:
    rider_id: str
    vehicle: Vehicle
    capacity: int                     # capacity left for these orders (round capacity minus held orders)
    origin_id: str
    end_id: str | None                # None = open route (Last stop)
    endpoint_kind: EndpointKind
    orders: tuple[Order, ...]         # the rider's own Pending orders only
    locations: dict[str, Location]    # every id above, with coordinates (memory only)


@dataclass
class RerouteResult:
    route: RiderRoute
    provenance: Provenance
    solve: SolveResult


def stops_for(inp: RerouteInput):
    """Navigation stops for the rider's orders (same grouping rule as round planning; no group is
    formed before 4C because no order carries a building id yet). Raises PRIORITY_CONFLICT if the
    rider holds more than one first-priority stop."""
    rnd = DeliveryRound(
        id="reroute", depots=Depots(inp.origin_id, inp.origin_id), orders=list(inp.orders), locations=inp.locations,
        riders=[Rider(id=inp.rider_id, vehicle=inp.vehicle, capacity=inp.capacity, start=StartKind.OFFICE,
                      endpoint=Endpoint(inp.endpoint_kind, None, True))])
    stops = build_stops(rnd, [o.id for o in inp.orders], max(inp.capacity, 1))
    _priority_check(stops, 1)
    return stops


def reroute(inp: RerouteInput, provider, *, profile: str, metric: str = "distance", time_limit_s: int = 10) -> RerouteResult:
    if not inp.orders:
        raise PlanningError("NOTHING_TO_REROUTE", "There are no Pending orders to recalculate.")
    if len(inp.orders) > inp.capacity:
        raise PlanningError("HELD_ORDERS_EXCEED_CAPACITY", "Your orders exceed your capacity for this round.")
    stops = stops_for(inp)
    vehicle = VehicleSpec(inp.rider_id, inp.capacity, inp.origin_id, inp.end_id)
    loc_ids = sorted({s.location_id for s in stops} | {inp.origin_id} | ({inp.end_id} if inp.end_id else set()))
    locs = [inp.locations[i] for i in loc_ids]
    matrix = provider.compute(locs, locs, profile)
    if not matrix.provenance.real_road:
        raise PlanningError("NOT_ROAD_DISTANCES", "The matrix is not real road data; a route is never saved from it.")
    by_rider = {inp.rider_id: matrix}
    _unroutable_check(stops, loc_ids, by_rider, open_routes=inp.end_id is None)
    try:
        _endpoint_check([vehicle], loc_ids, by_rider)
    except PlanningError as exc:
        if any(d.endswith(": start") for d in exc.details):
            raise PlanningError("UNROUTABLE_ORIGIN", "Your starting point has no road connection for your vehicle. "
                                "Choose another starting point. Nothing was changed.") from None
        raise PlanningError("UNROUTABLE_ENDPOINT", "Your destination has no road connection for your vehicle. "
                            "Nothing was changed.") from None
    result = solve([vehicle], stops, by_rider, metric=metric, time_limit_s=time_limit_s)
    route = assemble_route(inp.rider_id, 1, vehicle, inp.endpoint_kind, result.sequences[inp.rider_id], matrix)
    violations = check(inp, route)
    if violations:
        raise PlanningError("INTERNAL", "The recalculated route violated an invariant.", violations)
    return RerouteResult(route, matrix.provenance, result)


def check(inp: RerouteInput, route: RiderRoute) -> list[str]:
    """Independent invariants (spike `validate_plan`, rider scope)."""
    v: list[str] = []
    planned = route.order_ids()
    if sorted(planned) != sorted(o.id for o in inp.orders):
        v.append("the sequence is not exactly the rider's Pending orders")
    if len(planned) != len(set(planned)):
        v.append("an order appears twice")
    if len(planned) > inp.capacity:
        v.append("capacity exceeded")
    if route.start_location_id != inp.origin_id:
        v.append("the route does not start at the chosen origin")
    if route.end_location_id != inp.end_id:
        v.append("the route does not end at the confirmed endpoint")
    priority = {o.id for o in inp.orders if o.first_priority}
    prio_stops = [i for i, s in enumerate(route.stops) if priority & set(s.order_ids)]
    if prio_stops and prio_stops != [0]:
        v.append("the first-priority stop is not the first delivery")
    locks = {o.id: o.locked_rider_id for o in inp.orders if o.locked_rider_id}
    if any(r != inp.rider_id for r in locks.values()):
        v.append("an order is locked to another rider")
    return v
