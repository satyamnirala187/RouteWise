"""Criteria 3 and 4: separate starts/ends, all five endpoint options, confirmation gate (incl. API)."""

import pytest
from fastapi.testclient import TestClient

from routewise_spike.api import create_app
from routewise_spike.models import Endpoint, EndpointKind, StartKind
from routewise_spike.planner import PlanningError, optimize_round, route_cost

from .conftest import PROFILE


def test_each_rider_starts_and_ends_where_requested(real, make_round):
    rnd = make_round()
    assert len(rnd.active_riders()) >= 2 and len(rnd.orders) >= 8
    assert {r.start for r in rnd.riders} == {StartKind.OFFICE, StartKind.WAREHOUSE}
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert plan.routes["R1"].start_location_id == "office" and plan.routes["R1"].end_location_id == "home_r1"
    assert plan.routes["R2"].start_location_id == "warehouse" and plan.routes["R2"].end_location_id == "custom_r2"
    assert plan.routes["R3"].start_location_id == "warehouse" and plan.routes["R3"].end_location_id is None
    assert plan.distance_label.startswith("Road distances") and plan.provenance["real_road"]


def test_last_stop_adds_no_artificial_return_trip(real, make_round):
    rnd = make_round()
    locations = rnd.locations
    plan = optimize_round(rnd, real, profile=PROFILE)
    r3 = plan.routes["R3"]
    assert r3.stops, "fixture should give R3 at least one stop"
    path = [r3.start_location_id] + [s.location_id for s in r3.stops]
    matrix = real.compute(list(locations.values()), list(locations.values()), PROFILE)
    assert (r3.road_distance_m, r3.road_duration_s) == route_cost(matrix, path)
    with_return = route_cost(matrix, path + [r3.start_location_id])[0]
    assert r3.road_distance_m < with_return


@pytest.mark.parametrize(
    "endpoint, expected_end",
    [
        (Endpoint(EndpointKind.OFFICE, None, True), "office"),
        (Endpoint(EndpointKind.WAREHOUSE, None, True), "warehouse"),
        (Endpoint(EndpointKind.HOME, "home_r1", True), "home_r1"),
        (Endpoint(EndpointKind.CUSTOM, "custom_r2", True), "custom_r2"),
        (Endpoint(EndpointKind.LAST_STOP, None, True), None),
    ],
    ids=lambda x: x.kind.value if isinstance(x, Endpoint) else str(x),
)
def test_all_five_endpoint_options(real, make_round, endpoint, expected_end):
    rnd = make_round()
    rnd.rider("R1").endpoint = endpoint
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert plan.routes["R1"].end_location_id == expected_end
    assert plan.routes["R1"].endpoint_kind is endpoint.kind


@pytest.mark.parametrize(
    "endpoint, reason",
    [
        (None, "missing"),
        (Endpoint(EndpointKind.HOME, "home_r1", False), "unconfirmed"),
        (Endpoint(EndpointKind.HOME, None, True), "invalid_location"),
        (Endpoint(EndpointKind.CUSTOM, "not-a-resolved-location", True), "invalid_location"),
        (Endpoint(EndpointKind.LAST_STOP, None, False), "unconfirmed"),
    ],
    ids=["missing", "unconfirmed", "home-without-pin", "custom-unresolved", "last-stop-unconfirmed"],
)
def test_initial_optimization_waits_for_valid_confirmed_endpoints(real, make_round, endpoint, reason):
    rnd = make_round()
    rnd.rider("R2").endpoint = endpoint
    with pytest.raises(PlanningError) as exc:
        optimize_round(rnd, real, profile=PROFILE)
    assert exc.value.code == "ENDPOINTS_NOT_CONFIRMED"
    assert exc.value.details == [f"R2: {reason}"]


def test_removed_rider_does_not_block_the_gate(real, make_round):
    rnd = make_round()
    rnd.rider("R3").endpoint = None
    rnd.rider("R3").active = False
    rnd.rider("R1").capacity = 7  # keep total capacity >= 12 orders
    plan = optimize_round(rnd, real, profile=PROFILE)
    assert set(plan.routes) == {"R1", "R2"}


def test_api_boundary_blocks_until_every_rider_confirms(real, make_round):
    rnd = make_round(confirmed=False)
    client = TestClient(create_app(rnd, real, PROFILE))
    r = client.post("/rounds/phase0-demo/optimize")
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["code"] == "ENDPOINTS_NOT_CONFIRMED" and len(body["details"]) == 3
    home = rnd.locations["home_r1"]
    assert "home_r1" not in r.text and f"{home.lat}" not in r.text and f"{home.lng}" not in r.text  # no location leaks
    for rid, kind, loc in [("R1", "home", "home_r1"), ("R2", "custom", "custom_r2")]:
        assert client.put(f"/rounds/phase0-demo/riders/{rid}/endpoint",
                          json={"kind": kind, "location_id": loc, "confirm": True}).status_code == 200
    r = client.post("/rounds/phase0-demo/optimize")
    assert r.status_code == 409 and r.json()["detail"]["details"] == ["R3: unconfirmed"]
    client.put("/rounds/phase0-demo/riders/R3/endpoint", json={"kind": "last_stop", "confirm": True})
    r = client.post("/rounds/phase0-demo/optimize")
    assert r.status_code == 200
    assert sorted(o for route in r.json()["routes"].values() for o in route["orders"]) == [o.id for o in rnd.orders]
