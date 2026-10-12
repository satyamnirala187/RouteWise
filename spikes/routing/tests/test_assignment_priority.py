"""Criteria 5 and 6: equal/smart/manual modes, capacities, locks, single ownership, priority."""

import pytest

from routewise_spike.models import DistributionMode, Endpoint, EndpointKind, Order
from routewise_spike.planner import PlanningError, equal_bounds, optimize_round, validate_plan

from .conftest import PROFILE


def total_km(plan):
    return sum(r.road_distance_m for r in plan.routes.values()) / 1000


@pytest.mark.parametrize("mode", list(DistributionMode))
def test_every_order_assigned_exactly_once_in_every_mode(real, make_round, mode):
    rnd = make_round(mode=mode)
    if mode is DistributionMode.MANUAL:
        for i, o in enumerate(rnd.orders):
            o.locked_rider_id = ["R1", "R2", "R3"][i % 3]
    plan = optimize_round(rnd, real, profile=PROFILE)
    owners = [oid for r in plan.routes.values() for oid in r.order_ids()]
    assert sorted(owners) == sorted(o.id for o in rnd.orders) and len(owners) == len(set(owners))
    assert validate_plan(rnd, plan) == []


def test_equal_mode_balances_counts_and_smart_mode_minimises_road_distance(real, make_round):
    equal = optimize_round(make_round(mode=DistributionMode.EQUAL), real, profile=PROFILE)
    smart = optimize_round(make_round(mode=DistributionMode.SMART), real, profile=PROFILE)
    assert sorted(len(r.order_ids()) for r in equal.routes.values()) == [4, 4, 4]
    assert equal.warnings == []
    assert total_km(smart) <= total_km(equal)


def test_equal_bounds_respect_mixed_capacities():
    assert equal_bounds(12, {"a": 5, "b": 5, "c": 4}) == {"a": (3, 4), "b": (3, 4), "c": (3, 4)}
    assert equal_bounds(10, {"a": 2, "b": 10, "c": 10}) == {"a": (2, 2), "b": (3, 4), "c": (3, 4)}
    assert equal_bounds(0, {"a": 3}) == {"a": (0, 0)}


def test_mixed_capacities_are_respected(real, make_round):
    rnd = make_round(mode=DistributionMode.SMART)
    rnd.rider("R1").capacity, rnd.rider("R2").capacity, rnd.rider("R3").capacity = 2, 8, 2
    plan = optimize_round(rnd, real, profile=PROFILE)
    for rid, cap in [("R1", 2), ("R2", 8), ("R3", 2)]:
        assert len(plan.routes[rid].order_ids()) <= cap


def test_manual_mode_keeps_admin_assignments_and_only_sequences(real, make_round):
    rnd = make_round(mode=DistributionMode.MANUAL)
    wanted = {o.id: ["R1", "R2", "R3"][i % 3] for i, o in enumerate(rnd.orders)}
    for o in rnd.orders:
        o.locked_rider_id = wanted[o.id]
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert plan.assignments == wanted


def test_manual_mode_requires_every_assignment(real, make_round):
    rnd = make_round(mode=DistributionMode.MANUAL)
    rnd.orders[0].locked_rider_id = "R1"
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "MANUAL_ASSIGNMENT_MISSING" and len(exc.value.details) == 11


@pytest.mark.parametrize("mode", [DistributionMode.SMART, DistributionMode.EQUAL])
def test_manual_lock_survives_automatic_modes(real, make_round, mode):
    rnd = make_round(mode=mode)
    rnd.order("O09").locked_rider_id = "R3"  # Koramangala to the north-west rider
    rnd.order("O06").locked_rider_id = "R1"
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert plan.assignments["O09"] == "R3" and plan.assignments["O06"] == "R1"


def test_insufficient_total_capacity_is_explained_not_dropped(real, make_round):
    rnd = make_round()
    for r in rnd.riders:
        r.capacity = 3
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "INSUFFICIENT_CAPACITY" and "12 orders exceed total rider capacity 9" in exc.value.message


def test_locks_beyond_capacity_and_to_inactive_riders_are_rejected(real, make_round):
    rnd = make_round()
    for o in rnd.orders[:5]:
        o.locked_rider_id = "R3"  # capacity 4
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "LOCK_EXCEEDS_CAPACITY"

    rnd = make_round()
    rnd.rider("R3").active = False
    rnd.rider("R1").capacity = 8
    rnd.order("O01").locked_rider_id = "R3"
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "INVALID_LOCK"


def test_unresolved_pin_blocks_planning(real, make_round):
    rnd = make_round()
    rnd.orders.append(Order("O13", None))
    rnd.rider("R1").capacity = 6
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "UNRESOLVED_LOCATION" and exc.value.details == ["O13"]


# ------------------------------------------------------------------ priority (D05)


@pytest.mark.parametrize("order_id", ["O01", "O06", "O08", "O11"])
@pytest.mark.parametrize("mode", [DistributionMode.SMART, DistributionMode.EQUAL])
def test_priority_order_is_first_active_delivery_on_its_route(real, make_round, order_id, mode):
    rnd = make_round(mode=mode)
    rnd.order(order_id).first_priority = True
    plan = optimize_round(rnd, real, profile=PROFILE)
    route = plan.routes[plan.assignments[order_id]]
    assert order_id in route.stops[0].order_ids


def test_priority_with_lock_goes_first_on_the_locked_rider(real, make_round):
    rnd = make_round()
    rnd.order("O08").first_priority = True
    rnd.order("O08").locked_rider_id = "R2"
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert plan.routes["R2"].stops[0].order_ids == ["O08"]


def test_one_priority_per_rider_route_allows_three(real, make_round):
    rnd = make_round()
    for oid in ("O06", "O08", "O10"):
        rnd.order(oid).first_priority = True
    plan = optimize_round(rnd, real, profile=PROFILE)
    firsts = {r.stops[0].order_ids[0] for r in plan.routes.values() if r.stops}
    assert firsts == {"O06", "O08", "O10"}


def test_conflicting_priorities_are_reported_explicitly(real, make_round):
    rnd = make_round()
    for oid in ("O06", "O08"):
        rnd.order(oid).first_priority = True
        rnd.order(oid).locked_rider_id = "R1"
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "PRIORITY_CONFLICT" and "R1 has 2" in exc.value.details[0]

    rnd = make_round()
    for oid in ("O01", "O06", "O08", "O10"):
        rnd.order(oid).first_priority = True
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "PRIORITY_CONFLICT" and "only 3 riders" in exc.value.details[0]


def test_locked_priority_on_single_capacity_open_route(real, make_round):
    rnd = make_round()
    rnd.order("O08").first_priority = True
    rnd.order("O08").locked_rider_id = "R1"
    rnd.rider("R1").endpoint = Endpoint(EndpointKind.LAST_STOP, None, True)
    rnd.rider("R1").capacity = 1
    rnd.rider("R2").capacity = rnd.rider("R3").capacity = 6
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert plan.routes["R1"].order_ids() == ["O08"]
