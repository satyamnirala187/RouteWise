"""Parity between the accepted Phase 0 spike planner (spikes/routing, imported read-only) and
the application port (routewise_api.routing), on the recorded real DU North Campus matrices.

Exact sequences are not required where several optimal answers exist: the checks are that both
planners reach the same objective and satisfy every invariant, and that the port reproduces the
assignments recorded in the spike's accepted evidence."""

import json
import random
import sys

import pytest

from routewise_api.config import REPO_ROOT
from routewise_api.routing import domain as port_domain
from routewise_api.routing import planner as port_planner

from .recorded_matrix import RecordedDUProvider

SPIKE = REPO_ROOT / "spikes" / "routing"
EVIDENCE = SPIKE / "evidence"
KINDS = {"du-motor_scooter": "motor_scooter", "du-motorcycle": "motorcycle", "du-fleet": None}


@pytest.fixture(scope="module")
def spike():
    sys.path.insert(0, str(SPIKE))
    try:
        from routewise_spike import models, planner, scenario
        from routewise_spike.matrix.recorded import ByProfile, RecordedMatrixProvider
    finally:
        sys.path.remove(str(SPIKE))
    return {"models": models, "planner": planner, "scenario": scenario, "ByProfile": ByProfile,
            "Recorded": RecordedMatrixProvider}


def spike_provider(spike, kind):
    rec = spike["scenario"].RECORDED_VALHALLA
    m = spike["models"]
    if KINDS[kind]:
        return spike["Recorded"](rec[KINDS[kind]]), KINDS[kind]
    return (spike["ByProfile"]({c: spike["Recorded"](rec[c]) for c in ("motor_scooter", "motorcycle")}),
            {m.Vehicle.SCOOTER: "motor_scooter", m.Vehicle.BIKE: "motorcycle"})


def port_profile(kind):
    if KINDS[kind]:
        return KINDS[kind]
    return {port_domain.Vehicle.SCOOTER: "motor_scooter", port_domain.Vehicle.BIKE: "motorcycle"}


def to_port(rnd):
    """Copy a spike DeliveryRound into the port's identical domain classes."""
    def endpoint(e):
        return None if e is None else port_domain.Endpoint(port_domain.EndpointKind(e.kind.value), e.location_id, e.confirmed)

    riders = [port_domain.Rider(r.id, port_domain.Vehicle(r.vehicle.value), r.capacity, port_domain.StartKind(r.start.value),
                                endpoint(r.endpoint), r.active) for r in rnd.riders]
    orders = [port_domain.Order(o.id, o.location_id, o.building_id, port_domain.OrderStatus(o.status.value),
                                o.locked_rider_id, o.first_priority, o.completed_at) for o in rnd.orders]
    locations = {k: port_domain.Location(v.id, v.name, v.lat, v.lng) for k, v in rnd.locations.items()}
    return port_domain.DeliveryRound(rnd.id, port_domain.Depots(rnd.depots.office_location_id, rnd.depots.warehouse_location_id),
                                     riders, orders, locations, port_domain.DistributionMode(rnd.mode.value))


def both(spike, kind, rnd):
    sp, sprof = spike_provider(spike, kind)
    s = spike["planner"].optimize_round(rnd, sp, profile=sprof)
    port_rnd = to_port(rnd)
    p = port_planner.optimize_round(port_rnd, RecordedDUProvider(), profile=port_profile(kind))
    assert port_planner.validate_plan(port_rnd, p) == []
    assert spike["planner"].validate_plan(rnd, s) == []
    return s, p


def evidence(kind):
    return json.loads((EVIDENCE / f"scenario_run_{kind}.json").read_text())["steps"]


@pytest.mark.parametrize("kind", list(KINDS))
def test_port_reproduces_the_accepted_spike_evidence(spike, kind):
    steps = evidence(kind)
    sc, m = spike["scenario"], spike["models"]
    plans = {}
    for mode, step in ((m.DistributionMode.SMART, steps[1]), (m.DistributionMode.EQUAL, steps[2])):
        rnd = sc.phase0_round(mode=mode, area="du_north")
        rnd.order("O08").first_priority = True
        s, p = both(spike, kind, rnd)
        plans[mode] = p
        assert p.provenance["objective"] == s.provenance["objective"]
        assert p.distance_label == step["distance_label"] == s.distance_label
        if p.assignments != step["assignments"]:  # an equivalent optimum is acceptable, a worse one is not
            assert sum(r.road_distance_m for r in p.routes.values()) == round(sum(step["km"].values()) * 1000)
        else:
            assert {k: v.road_distance_m / 1000 for k, v in p.routes.items()} == step["km"]
        assert any(r.stops and r.stops[0].order_ids[0] == "O08" for r in p.routes.values())
    # Manual: the evidence's equal-plan owners with O12 moved, as the spike scenario did.
    manual = sc.phase0_round(mode=m.DistributionMode.MANUAL, area="du_north")
    for oid, rid in steps[2]["assignments"].items():
        manual.order(oid).locked_rider_id = rid
    owner = steps[2]["assignments"]["O12"]
    load = {r.id: sum(1 for o in manual.orders if o.locked_rider_id == r.id) for r in manual.riders}
    manual.order("O12").locked_rider_id = next(r.id for r in manual.riders if r.id != owner and load[r.id] < r.capacity)
    s, p = both(spike, kind, manual)
    assert p.assignments == steps[3]["assignments"] == s.assignments
    assert p.provenance["objective"] == s.provenance["objective"]


@pytest.mark.parametrize("seed", range(10))
def test_port_and_spike_agree_on_generated_rounds(spike, seed):
    """Random DU rounds: subsets of public points, every mode, capacities, locks and priority."""
    rng = random.Random(seed)
    sc, m = spike["scenario"], spike["models"]
    locs = sc.load_locations(sc.DU_LOCATIONS_FILE)
    points = [k for k in locs if k not in ("office", "warehouse", "home_r1", "custom_r2", "gps_r1", "daulat_ram_centroid")]
    kinds = [m.EndpointKind.HOME, m.EndpointKind.CUSTOM, m.EndpointKind.LAST_STOP, m.EndpointKind.OFFICE,
             m.EndpointKind.WAREHOUSE]
    n_riders = rng.randint(1, 3)
    riders = []
    for i in range(n_riders):
        k = rng.choice(kinds)
        loc = {"HOME": "home_r1", "CUSTOM": "custom_r2"}.get(k.name)
        riders.append(m.Rider(f"R{i + 1}", rng.choice(list(m.Vehicle)), rng.randint(3, 6),
                              rng.choice(list(m.StartKind)), m.Endpoint(k, loc, True)))
    n_orders = rng.randint(3, min(len(points), sum(r.capacity for r in riders)))
    orders = [m.Order(f"O{i:02d}", rng.choice(points)) for i in range(n_orders)]
    mode = rng.choice(list(m.DistributionMode))
    if mode is m.DistributionMode.MANUAL:
        load = {r.id: 0 for r in riders}
        for o in orders:
            r = rng.choice([r for r in riders if load[r.id] < r.capacity])
            o.locked_rider_id, load[r.id] = r.id, load[r.id] + 1
    elif rng.random() < 0.5:
        orders[0].locked_rider_id = riders[0].id
    if rng.random() < 0.5:
        orders[-1].first_priority = True
    rnd = m.DeliveryRound(f"gen-{seed}", m.Depots("office", "warehouse"), riders, orders, locs, mode)
    s, p = both(spike, "du-fleet", rnd)
    assert p.provenance["objective"] == s.provenance["objective"]
    assert sum(r.road_distance_m for r in p.routes.values()) == sum(r.road_distance_m for r in s.routes.values())
