"""Criterion 9 (planner side): missing road edges are forbidden, never zero; synthetic
matrices are always labelled as not road distances."""

import pytest

from routewise_spike.matrix import ElementStatus
from routewise_spike.matrix.synthetic import SyntheticMatrixProvider
from routewise_spike.models import DistributionMode
from routewise_spike.planner import PlanningError, optimize_round

from .conftest import PROFILE


def consecutive_pairs(route):
    path = [route.start_location_id] + [s.location_id for s in route.stops]
    if route.end_location_id:
        path.append(route.end_location_id)
    return set(zip(path, path[1:]))


def test_synthetic_plan_is_never_labelled_as_road(make_round, synthetic):
    plan = optimize_round(make_round(), synthetic, profile="synthetic")
    assert plan.distance_label.startswith("SYNTHETIC — NOT ROAD DISTANCES")
    assert plan.provenance["real_road"] is False


def test_planner_avoids_unreachable_directed_edges(make_round):
    base = SyntheticMatrixProvider()
    plan = optimize_round(make_round(), base, profile="synthetic")
    used = set().union(*(consecutive_pairs(r) for r in plan.routes.values()))
    blocked = {p for p in used if p[0] != p[1]}
    blocked_provider = SyntheticMatrixProvider(unreachable=blocked)
    plan2 = optimize_round(make_round(), blocked_provider, profile="synthetic")
    used2 = set().union(*(consecutive_pairs(r) for r in plan2.routes.values()))
    assert not (used2 & blocked), "a missing road edge was used"
    assert sorted(plan2.assignments) == sorted(o.id for o in make_round().orders)


def test_missing_edge_cost_is_none_not_zero(locations):
    m = SyntheticMatrixProvider(unreachable={("office", "ub_city")}).compute(
        [locations["office"]], [locations["ub_city"]], "synthetic")
    assert m.get("office", "ub_city").status is ElementStatus.NO_ROUTE
    assert m.cost("office", "ub_city") is None


def test_isolated_stop_fails_explicitly_without_dropping_orders(make_round):
    rnd = make_round(mode=DistributionMode.SMART)
    isolated = rnd.order("O11").location_id
    cut = {(o, isolated) for o in rnd.locations if o != isolated}
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, SyntheticMatrixProvider(unreachable=cut),
                       profile="synthetic", time_limit_s=2)
    # Caught before solving, with the exact order to fix (pin correction), not a generic failure.
    assert exc.value.code == "UNROUTABLE_LOCATION"
    assert "No order was dropped" in exc.value.message
    assert exc.value.details == ["O11"]


def test_infeasible_combination_still_reports_no_feasible_plan(make_round):
    """Every pin routable, but the only way into one stop is from a start that can't take it."""
    rnd = make_round(mode=DistributionMode.SMART)
    target = rnd.order("O11").location_id
    cut = {(o, target) for o in rnd.locations if o not in (target, "office")}  # only reachable from Office (R1)
    rnd.order("O11").locked_rider_id = "R2"  # ...but locked to a Warehouse rider
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, SyntheticMatrixProvider(unreachable=cut), profile="synthetic", time_limit_s=2)
    assert exc.value.code == "NO_FEASIBLE_PLAN" and "No order was dropped" in exc.value.message
