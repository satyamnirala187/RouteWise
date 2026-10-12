"""Rider-only rerouting (postpone, origin change, endpoint change).

Freezes package ownership and every other rider's route object. Only the
requesting rider's Pending orders are resequenced. Postponed orders stay
assigned but leave the active sequence until explicitly returned to Pending (D08).
Reoptimization needs a live matrix: on provider failure the last valid plan is
kept and marked as awaiting recalculation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .gate import endpoint_gate_issues
from .matrix.base import MatrixProvider, ProviderError
from .models import DeliveryRound, OrderStatus, Plan
from .planner import (
    PlanningError,
    VehicleSpec,
    assemble_route,
    build_stops,
    fingerprint,
    solve,
    validate_plan,
)


@dataclass(frozen=True)
class RerouteOrigin:
    kind: str  # current_position | last_completed_stop | configured_start | confirmed_pin
    location_id: str
    label: str


class OriginConfirmationRequired(Exception):
    pass


def choose_origin(
    rnd: DeliveryRound,
    plan: Plan,
    rider_id: str,
    *,
    gps_location_id: str | None = None,
    rider_confirmed: RerouteOrigin | None = None,
) -> RerouteOrigin:
    """Fresh GPS first; else last completed stop (labelled fallback); else ask the rider."""
    if gps_location_id:
        return RerouteOrigin("current_position", gps_location_id, "Current position (fresh, location permission granted)")
    completed = [
        rnd.order(oid)
        for oid, rid in plan.assignments.items()
        if rid == rider_id and rnd.order(oid).status is OrderStatus.COMPLETED
    ]
    if completed:
        last = max(completed, key=lambda o: o.completed_at or "")
        return RerouteOrigin(
            "last_completed_stop",
            last.location_id,
            "Fallback: last completed stop (current position unavailable)",
        )
    if rider_confirmed and rider_confirmed.kind in ("configured_start", "confirmed_pin"):
        return rider_confirmed
    raise OriginConfirmationRequired(
        "No current position and no completed stop: ask the rider to confirm a current pin or their configured start."
    )


@dataclass
class RerouteOutcome:
    plan: Plan
    recalculated: bool
    message: str


def reroute_rider(
    rnd: DeliveryRound,
    plan: Plan,
    rider_id: str,
    provider: MatrixProvider,
    *,
    profile: str | dict,
    origin: RerouteOrigin,
    metric: str = "distance",
    time_limit_s: int = 10,
) -> RerouteOutcome:
    rider = rnd.rider(rider_id)
    issues = [i for i in endpoint_gate_issues(rnd) if i.rider_id == rider_id]
    if issues:
        raise PlanningError("ENDPOINTS_NOT_CONFIRMED", "Confirm a valid endpoint before rerouting.", [i.reason for i in issues])
    if origin.location_id not in rnd.locations:
        raise PlanningError("UNRESOLVED_LOCATION", "Reroute origin is not a resolved location.")

    owned = [oid for oid, rid in plan.assignments.items() if rid == rider_id]
    pending = [o for o in owned if rnd.order(o).status is OrderStatus.PENDING]
    postponed = [o for o in owned if rnd.order(o).status is OrderStatus.POSTPONED]
    completed = [o for o in owned if rnd.order(o).status is OrderStatus.COMPLETED]

    vehicle = VehicleSpec(rider_id, rider.capacity, origin.location_id, rnd.end_location_id(rider.endpoint))
    stops = build_stops(rnd, pending, rider.capacity)
    loc_ids = sorted({s.location_id for s in stops} | {vehicle.start_location_id}
                     | ({vehicle.end_location_id} if vehicle.end_location_id else set()))
    locs = [rnd.locations[i] for i in loc_ids]
    old = plan.routes[rider_id]
    try:
        rider_profile = profile if isinstance(profile, str) else profile[rider.vehicle]
        matrix = provider.compute(locs, locs, rider_profile)
    except ProviderError as exc:
        return RerouteOutcome(
            plan, False, f"Awaiting recalculation: {type(exc).__name__}. Last valid plan v{plan.version} kept; reconnect and retry."
        )
    result = solve([vehicle], stops, matrix, metric=metric, time_limit_s=time_limit_s)

    route = assemble_route(rider_id, old.version + 1, vehicle, rider.endpoint.kind, result.sequences[rider_id], matrix)
    route.origin_kind, route.origin_label = origin.kind, origin.label
    route.postponed_order_ids, route.completed_order_ids = postponed, completed

    new_plan = Plan(
        round_id=plan.round_id,
        version=plan.version + 1,
        input_fingerprint=fingerprint(rnd),
        mode=plan.mode,
        routes={**plan.routes, rider_id: route},  # other riders: same objects, untouched
        assignments=dict(plan.assignments),
        distance_label=plan.distance_label if matrix.provenance.real_road else matrix.provenance.label(),
        provenance=plan.provenance | {"last_reroute": matrix.provenance.as_dict() | {"rider_id": rider_id}},
        warnings=list(plan.warnings),
    )
    violations = validate_plan(rnd, new_plan)
    violations += [f"{o} is not Pending but in the new active sequence"
                   for o in route.order_ids() if rnd.order(o).status is not OrderStatus.PENDING]
    if violations or new_plan.assignments != plan.assignments:
        raise PlanningError("INTERNAL", "Reroute violated an invariant.", violations)
    return RerouteOutcome(new_plan, True, f"Rerouted {rider_id} from {origin.kind}")
