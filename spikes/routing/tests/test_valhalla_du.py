"""Local Valhalla (OSM) evidence for the confirmed delivery area, DU North Campus, Delhi.

Recorded matrices were produced by the local, self-hosted Valhalla build (no network,
no paid service). Data © OpenStreetMap contributors, ODbL 1.0.
"""

import json
import math
import os
from pathlib import Path

import pytest

from routewise_spike.matrix import ElementStatus, ProviderUnavailable
from routewise_spike.matrix.recorded import RecordedMatrixProvider
from routewise_spike.matrix.valhalla_local import ATTRIBUTION, ValhallaLocalProvider, to_recording
from routewise_spike.scenario import RECORDED_VALHALLA, REPO_ROOT

COSTINGS = ("motor_scooter", "motorcycle")


def bline_m(a, b):
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b.lng - a.lng) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


@pytest.fixture(scope="module")
def recorded():
    return {c: RecordedMatrixProvider(RECORDED_VALHALLA[c]) for c in COSTINGS}


def full(provider, du_locations):
    pts = list(du_locations.values())
    return provider.compute(pts, pts, "recorded")


@pytest.mark.parametrize("costing", COSTINGS)
def test_recording_is_real_local_valhalla_with_attribution(recorded, du_locations, costing):
    m = full(recorded[costing], du_locations)
    p = m.provenance
    assert p.real_road and p.recorded and p.profile == costing
    assert p.provider.startswith("valhalla-local") and "OpenStreetMap" in p.notes and "ODbL" in p.notes
    assert recorded[costing].meta["test_area"].startswith("DU North Campus")
    assert len(du_locations) >= 16 and p.element_count == len(du_locations) ** 2


@pytest.mark.parametrize("costing", COSTINGS)
def test_directed_asymmetry_and_no_road_shorter_than_straight_line(recorded, du_locations, costing):
    m = full(recorded[costing], du_locations)
    ids = list(du_locations)
    ok = [(a, b) for a in ids for b in ids if a != b and m.get(a, b).status is ElementStatus.OK]
    assert ok, "no routable pairs"
    asym = [(a, b) for a, b in ok if a < b and (b, a) in set(ok)
            and abs(m.get(a, b).distance_m - m.get(b, a).distance_m) > 50]
    assert asym, "expected directed asymmetry on a real road network"
    for a, b in ok:  # snapping can shave a little; a road path is never much shorter than the b-line
        assert m.get(a, b).distance_m >= 0.8 * bline_m(du_locations[a], du_locations[b]) - 300, (a, b)


def test_scooter_and_motorcycle_profiles_really_differ(recorded, du_locations):
    s, c = (full(recorded[k], du_locations) for k in COSTINGS)
    ids = list(du_locations)
    diffs = [(a, b) for a in ids for b in ids if a != b
             and s.get(a, b).status is ElementStatus.OK and c.get(a, b).status is ElementStatus.OK
             and s.get(a, b).duration_s != c.get(a, b).duration_s]
    assert diffs, "motor_scooter and motorcycle should not give identical travel times"


def test_recording_round_trips(tmp_path, du_locations):
    from routewise_spike.matrix.synthetic import SyntheticMatrixProvider

    pts = list(du_locations.values())[:4]
    m = SyntheticMatrixProvider(unreachable={(pts[0].id, pts[1].id)}).compute(pts, pts, "x")
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(to_recording(m, pts, {"test_area": "unit"})))
    back = RecordedMatrixProvider(path).compute(pts, pts, "x")
    assert back.get(pts[0].id, pts[1].id).status is ElementStatus.NO_ROUTE
    assert back.get(pts[1].id, pts[0].id) == m.get(pts[1].id, pts[0].id)
    assert back.provenance.real_road is False  # synthetic stays labelled synthetic after replay


class FakeActor:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.queries = response, error, []

    def matrix(self, query):
        self.queries.append(json.loads(query))
        if self.error:
            raise self.error
        return self.response


def test_adapter_sends_two_wheeler_costing_and_parses_nulls(du_locations):
    a, b = du_locations["office"], du_locations["warehouse"]
    resp = json.dumps({"units": "kilometers", "sources_to_targets": [
        [{"from_index": 0, "to_index": 0, "distance": 0.0, "time": 0},
         {"from_index": 0, "to_index": 1, "distance": None, "time": None}],
        [{"from_index": 1, "to_index": 0, "distance": 4.321, "time": 600},
         {"from_index": 1, "to_index": 1, "distance": 0.0, "time": 0}]]})
    actor = FakeActor(resp)
    m = ValhallaLocalProvider("unused", actor=actor).compute([a, b], [a, b], "motor_scooter")
    q = actor.queries[0]
    assert q["costing"] == "motor_scooter" and q["units"] == "kilometers" and set(q) == {"sources", "targets", "costing", "units"}
    assert m.get("office", "warehouse").status is ElementStatus.NO_ROUTE and m.cost("office", "warehouse") is None
    assert m.get("warehouse", "office").distance_m == 4321
    assert ATTRIBUTION in m.provenance.notes


def test_adapter_rejects_bicycle_and_wraps_engine_errors(du_locations):
    a = du_locations["office"]
    with pytest.raises(ValueError):
        ValhallaLocalProvider("unused", actor=FakeActor("{}")).compute([a], [a], "bicycle")
    with pytest.raises(ProviderUnavailable):
        ValhallaLocalProvider("unused", actor=FakeActor(error=RuntimeError("No suitable edges near location"))).compute(
            [a], [a], "motorcycle")


TILES = REPO_ROOT / "spikes" / "valhalla" / "data" / "valhalla_tiles"


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("ROUTEWISE_LIVE_TESTS") != "1" or not TILES.is_dir(),
                    reason="set ROUTEWISE_LIVE_TESTS=1 and build local tiles (spikes/valhalla/build_tiles.sh)")
@pytest.mark.parametrize("costing", COSTINGS)
def test_live_local_valhalla_matches_recording(du_locations, recorded, costing):
    pts = list(du_locations.values())
    live = ValhallaLocalProvider(TILES).compute(pts, pts, costing)
    rec = full(recorded[costing], du_locations)
    assert all(live.get(a.id, b.id) == rec.get(a.id, b.id) for a in pts for b in pts if a.id != b.id)


# ------------------------------------------------------------------ mixed fleet: per-vehicle profiles


def fleet_profiles():
    from routewise_spike.models import Vehicle

    return {Vehicle.SCOOTER: "motor_scooter", Vehicle.BIKE: "motorcycle"}


def test_mixed_fleet_plans_each_rider_on_its_own_profile(recorded):
    from routewise_spike.matrix.recorded import ByProfile
    from routewise_spike.planner import optimize_round, route_cost, validate_plan
    from routewise_spike.reroute import RerouteOrigin, reroute_rider
    from routewise_spike.scenario import phase0_round

    rnd = phase0_round(area="du_north")  # R1, R3 scooters; R2 bike (motorbike)
    provider = ByProfile(recorded)
    plan = optimize_round(rnd, provider, profile=fleet_profiles())
    assert validate_plan(rnd, plan) == []
    assert "motor_scooter" in plan.provenance["profile"] and "motorcycle" in plan.provenance["profile"]
    pts = list(rnd.locations.values())
    by_profile = {c: recorded[c].compute(pts, pts, c) for c in COSTINGS}
    for rid, route in plan.routes.items():
        prof = fleet_profiles()[rnd.rider(rid).vehicle]
        path = [route.start_location_id] + [s.location_id for s in route.stops] + (
            [route.end_location_id] if route.end_location_id else [])
        assert (route.road_distance_m, route.road_duration_s) == route_cost(by_profile[prof], path), rid
    out = reroute_rider(rnd, plan, "R2", provider, profile=fleet_profiles(),
                        origin=RerouteOrigin("configured_start", "warehouse", "rider-confirmed start"))
    assert out.recalculated and out.plan.provenance["last_reroute"]["profile"] == "motorcycle"


def test_edge_missing_for_one_profile_is_never_used_by_that_vehicle(du_locations):
    from routewise_spike.matrix.recorded import ByProfile
    from routewise_spike.matrix.synthetic import SyntheticMatrixProvider
    from routewise_spike.models import Vehicle
    from routewise_spike.planner import optimize_round
    from routewise_spike.scenario import phase0_round

    rnd = phase0_round(area="du_north")
    base = optimize_round(rnd, SyntheticMatrixProvider(), profile="synthetic")
    r2 = base.routes["R2"]
    path = [r2.start_location_id] + [s.location_id for s in r2.stops] + [r2.end_location_id]
    blocked = {p for p in zip(path, path[1:]) if p[0] != p[1]}
    provider = ByProfile({"motor_scooter": SyntheticMatrixProvider(),
                          "motorcycle": SyntheticMatrixProvider(unreachable=blocked)})
    plan = optimize_round(phase0_round(area="du_north"), provider,
                          profile={Vehicle.SCOOTER: "motor_scooter", Vehicle.BIKE: "motorcycle"})
    nr2 = plan.routes["R2"]
    new_path = [nr2.start_location_id] + [s.location_id for s in nr2.stops] + [nr2.end_location_id]
    assert not (set(zip(new_path, new_path[1:])) & blocked)
    assert plan.distance_label.startswith("SYNTHETIC")


def test_campus_centroid_pin_is_reported_as_unroutable(recorded):
    """Real finding: the Daulat Ram College centroid snaps to an isolated internal campus road."""
    from routewise_spike.planner import PlanningError, optimize_round
    from routewise_spike.scenario import phase0_round

    for costing in COSTINGS:
        rnd = phase0_round(area="du_north")
        rnd.order("O09").location_id = "daulat_ram_centroid"
        with pytest.raises(PlanningError) as exc:
            optimize_round(rnd, recorded[costing], profile="recorded")
        assert exc.value.code == "UNROUTABLE_LOCATION" and exc.value.details == ["O09"]
