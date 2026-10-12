"""Criteria 7 and 8: rider-only reroute, origin fallback, endpoint change, postponed return,
same-building navigation stops, stale plan protection."""

import pytest

from routewise_spike.matrix import ProviderUnavailable
from routewise_spike.models import DistributionMode, Endpoint, EndpointKind, Order, OrderStatus
from routewise_spike.planner import PlanStore, StalePlanError, build_stops, optimize_round
from routewise_spike.reroute import (
    OriginConfirmationRequired,
    RerouteOrigin,
    choose_origin,
    reroute_rider,
)

from .conftest import PROFILE


@pytest.fixture
def planned(real, make_round):
    rnd = make_round()
    return rnd, optimize_round(rnd, real, profile=PROFILE)


def complete(rnd, oid, at="2026-10-12T05:00:00Z"):
    o = rnd.order(oid)
    o.status, o.completed_at = OrderStatus.COMPLETED, at


def snapshot(plan, rider_id):
    return {k: (v.version, [s.order_ids for s in v.stops], v.road_distance_m) for k, v in plan.routes.items() if k != rider_id}


def test_postpone_and_reroute_changes_only_that_riders_active_sequence(real, planned):
    rnd, plan = planned
    r1 = plan.routes["R1"]
    assert len(r1.order_ids()) >= 3
    first, second = r1.order_ids()[0], r1.order_ids()[1]
    complete(rnd, first)
    rnd.order(second).status = OrderStatus.POSTPONED
    before_others = snapshot(plan, "R1")

    out = reroute_rider(rnd, plan, "R1", real, profile=PROFILE,
                        origin=choose_origin(rnd, plan, "R1", gps_location_id="gps_r1"))
    new = out.plan
    assert out.recalculated and new.version == plan.version + 1
    assert new.assignments == plan.assignments  # package ownership preserved
    assert snapshot(new, "R1") == before_others
    assert all(new.routes[k] is plan.routes[k] for k in ("R2", "R3"))
    nr1 = new.routes["R1"]
    assert nr1.version == r1.version + 1 and nr1.origin_kind == "current_position"
    assert nr1.start_location_id == "gps_r1" and nr1.end_location_id == "home_r1"
    assert nr1.completed_order_ids == [first] and nr1.postponed_order_ids == [second]
    assert first not in nr1.order_ids() and second not in nr1.order_ids()
    assert sorted(nr1.order_ids()) == sorted(set(r1.order_ids()) - {first, second})


def test_origin_fallback_is_explicit(real, planned):
    rnd, plan = planned
    with pytest.raises(OriginConfirmationRequired):
        choose_origin(rnd, plan, "R1")
    confirmed = RerouteOrigin("configured_start", "office", "Rider confirmed configured start")
    assert choose_origin(rnd, plan, "R1", rider_confirmed=confirmed) is confirmed
    first, second = plan.routes["R1"].order_ids()[:2]
    complete(rnd, first, "2026-10-12T05:00:00Z")
    complete(rnd, second, "2026-10-12T05:20:00Z")
    o = choose_origin(rnd, plan, "R1")
    assert o.kind == "last_completed_stop" and o.label.startswith("Fallback")
    assert o.location_id == rnd.order(second).location_id
    assert choose_origin(rnd, plan, "R1", gps_location_id="gps_r1").kind == "current_position"


def test_endpoint_change_reroutes_only_that_rider(real, planned):
    rnd, plan = planned
    rnd.rider("R2").endpoint = Endpoint(EndpointKind.WAREHOUSE, None, True)
    origin = RerouteOrigin("configured_start", "warehouse", "Rider confirmed configured start")
    out = reroute_rider(rnd, plan, "R2", real, profile=PROFILE, origin=origin)
    assert out.plan.routes["R2"].end_location_id == "warehouse"
    assert out.plan.assignments == plan.assignments
    assert all(out.plan.routes[k] is plan.routes[k] for k in ("R1", "R3"))


def test_unconfirmed_endpoint_change_cannot_reroute(real, planned):
    rnd, plan = planned
    rnd.rider("R2").endpoint = Endpoint(EndpointKind.CUSTOM, None, True)
    with pytest.raises(Exception) as exc:
        reroute_rider(rnd, plan, "R2", real, profile=PROFILE,
                      origin=RerouteOrigin("configured_start", "warehouse", ""))
    assert getattr(exc.value, "code", "") == "ENDPOINTS_NOT_CONFIRMED"


def test_provider_failure_keeps_last_valid_plan(planned):
    rnd, plan = planned

    class Offline:
        name = "offline"

        def compute(self, *a, **k):
            raise ProviderUnavailable("no connectivity")

    out = reroute_rider(rnd, plan, "R1", Offline(), profile=PROFILE,
                        origin=RerouteOrigin("configured_start", "office", ""))
    assert not out.recalculated and out.plan is plan
    assert out.message.startswith("Awaiting recalculation")


def test_postponed_order_returns_only_when_explicitly_pending(real, planned):
    rnd, plan = planned
    oid = plan.routes["R1"].order_ids()[-1]
    rnd.order(oid).status = OrderStatus.POSTPONED
    origin = RerouteOrigin("configured_start", "office", "")
    p2 = reroute_rider(rnd, plan, "R1", real, profile=PROFILE, origin=origin).plan
    assert oid not in p2.routes["R1"].order_ids() and oid in p2.routes["R1"].postponed_order_ids
    rnd.order(oid).status = OrderStatus.PENDING
    p3 = reroute_rider(rnd, p2, "R1", real, profile=PROFILE, origin=origin).plan
    assert oid in p3.routes["R1"].order_ids() and p3.assignments[oid] == "R1"


def test_stale_plan_cannot_overwrite_newer_state(real, make_round):
    rnd = make_round()
    store = PlanStore()
    plan = optimize_round(rnd, real, profile=PROFILE)
    rnd.order("O01").status = OrderStatus.POSTPONED  # status changed during the solve
    with pytest.raises(StalePlanError):
        store.commit(rnd, plan)
    rnd.order("O01").status = OrderStatus.PENDING
    store.commit(rnd, plan)
    with pytest.raises(StalePlanError):
        store.commit(rnd, plan)  # same version again


# ------------------------------------------------------------------ same building (R20)


def test_same_building_orders_share_one_stop_but_count_two_capacity_units(real, make_round):
    rnd = make_round()
    stops = build_stops(rnd, [o.id for o in rnd.orders], 5)
    ub = [s for s in stops if s.building_id == rnd.order("O02").building_id]
    assert len(ub) == 1 and ub[0].order_ids == ["O02", "O03"] and ub[0].demand == 2
    plan = optimize_round(rnd, real, profile=PROFILE)
    owner = plan.assignments["O02"]
    assert plan.assignments["O03"] == owner
    nav = [s for s in plan.routes[owner].stops if s.location_id == rnd.order("O02").location_id]
    assert len(nav) == 1 and nav[0].order_ids == ["O02", "O03"]


def test_building_group_counts_two_capacity_units(real, make_round):
    rnd = make_round()
    caps = {"R1": 5, "R2": 5, "R3": 2}  # total exactly 12 orders
    for rid, cap in caps.items():
        rnd.rider(rid).capacity = cap
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert {rid: len(r.order_ids()) for rid, r in plan.routes.items()} == caps
    assert plan.assignments["O02"] == plan.assignments["O03"]

    rnd = make_round()
    rnd.order("O02").locked_rider_id = rnd.order("O03").locked_rider_id = "R3"
    rnd.rider("R3").capacity, rnd.rider("R1").capacity, rnd.rider("R2").capacity = 1, 6, 6
    with pytest.raises(Exception) as exc:  # one navigation stop still needs two units
        optimize_round(rnd, real, profile=PROFILE)
    assert getattr(exc.value, "code", "") == "LOCK_EXCEEDS_CAPACITY"


def test_proximity_alone_does_not_group(make_round):
    rnd = make_round()
    rnd.orders.append(Order("O13", rnd.order("O02").location_id, None))  # same point, no validated building id
    stops = build_stops(rnd, ["O02", "O03", "O13"], 5)
    assert sorted(s.order_ids for s in stops) == [["O02", "O03"], ["O13"]]


def test_manually_split_building_is_not_merged(real, make_round):
    rnd = make_round()
    rnd.order("O02").locked_rider_id = "R1"
    rnd.order("O03").locked_rider_id = "R2"
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert plan.assignments["O02"] == "R1" and plan.assignments["O03"] == "R2"


def test_shared_stop_partial_completion_keeps_independent_statuses(real, make_round):
    rnd = make_round()
    rnd.order("O02").locked_rider_id = rnd.order("O03").locked_rider_id = "R3"
    plan = optimize_round(rnd, real, profile=PROFILE)
    complete(rnd, "O02")
    out = reroute_rider(rnd, plan, "R3", real, profile=PROFILE,
                        origin=choose_origin(rnd, plan, "R3"))
    r3 = out.plan.routes["R3"]
    assert rnd.order("O02").status is OrderStatus.COMPLETED
    assert rnd.order("O03").status is OrderStatus.PENDING
    assert r3.completed_order_ids == ["O02"]
    assert [s.order_ids for s in r3.stops if s.location_id == rnd.order("O03").location_id] == [["O03"]]
