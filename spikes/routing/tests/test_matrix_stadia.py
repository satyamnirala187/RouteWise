"""Stadia matrix adapter against mocked HTTP shaped by Stadia's published OpenAPI schema.
No live calls: every request goes to an httpx.MockTransport."""

import json

import httpx
import pytest

from routewise_spike.matrix import (
    ElementStatus,
    ProviderAuthError,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderRequestTooLarge,
    ProviderTimeout,
    ProviderUnavailable,
)
from routewise_spike.matrix.stadia import ENDPOINT, ProviderRequestRejected, StadiaMatrixProvider
from routewise_spike.models import DistributionMode
from routewise_spike.planner import optimize_round

KEY = "stadia-test-key-not-real"


def cells(n_o, n_d, *, null=(), km=lambda i, j: 1.0 + i + j / 1000):
    return [[{"from_index": i, "to_index": j,
              "distance": None if (i, j) in null else (0.0 if i == j and n_o == n_d else km(i, j)),
              "time": None if (i, j) in null else (0 if i == j and n_o == n_d else 60 * (i + 1) + j)}
             for j in range(n_d)] for i in range(n_o)]


def ok(req):
    body = json.loads(req.content)
    no, nd = len(body["sources"]), len(body["targets"])
    return httpx.Response(200, json={"sources": body["sources"], "targets": body["targets"],
                                     "sources_to_targets": cells(no, nd), "units": "kilometers"})


def stadia(handler, **kw):
    return StadiaMatrixProvider(KEY, client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def test_request_shape_matches_published_schema(locations):
    seen = {}

    def handler(req):
        seen["url"], seen["body"] = req.url, json.loads(req.content)
        return ok(req)

    pts = [locations[i] for i in ("office", "ub_city", "forum_koramangala")]
    m = stadia(handler).compute(pts, pts, "motor_scooter")
    assert str(seen["url"]).startswith(ENDPOINT) and seen["url"].params["api_key"] == KEY
    body = seen["body"]
    assert body["costing"] == "motor_scooter" and body["units"] == "km"
    assert body["sources"][0] == {"lat": 12.9796, "lon": 77.5906}
    assert set(body) == {"sources", "targets", "costing", "units"}  # coordinates only, no customer data
    assert m.get("office", "ub_city").distance_m == 1001  # 1.001 km -> metres
    assert m.provenance.real_road and m.provenance.profile == "motor_scooter"
    assert "transient" in m.provenance.notes


def test_motorcycle_costing_options_are_namespaced(locations):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return ok(req)

    pts = [locations["office"], locations["ub_city"]]
    stadia(handler, costing_options={"use_highways": 0.5}).compute(pts, pts, "motorcycle")
    assert seen["body"]["costing_options"] == {"motorcycle": {"use_highways": 0.5}}


@pytest.mark.parametrize("profile", ["auto", "bicycle", "pedestrian", "car_proxy"])
def test_only_two_wheeler_costings_are_allowed(locations, profile):
    with pytest.raises(ValueError):
        stadia(ok).compute([locations["office"]], [locations["ub_city"]], profile)


@pytest.mark.parametrize("n, batches", [(25, 1), (26, 4), (57, 9), (110, 25)])
def test_batches_stay_within_standard_625_elements_and_bill_exactly_n_squared(n, batches):
    from routewise_spike.models import Location

    sizes = []

    def handler(req):
        body = json.loads(req.content)
        sizes.append(len(body["sources"]) * len(body["targets"]))
        return ok(req)

    pts = [Location(f"p{i}", "", 12.95 + i / 2000, 77.60) for i in range(n)]
    p = stadia(handler)
    m = p.compute(pts, pts, "motor_scooter")
    assert len(sizes) == batches == p.requests_made and max(sizes) <= 625
    assert sum(sizes) == n * n == len(m.elements)  # tiling adds no billable elements


def test_null_distance_is_no_route_never_zero(locations):
    def handler(req):
        body = json.loads(req.content)
        return httpx.Response(200, json={"sources": body["sources"], "targets": body["targets"],
                                         "sources_to_targets": cells(2, 2, null={(0, 1)}), "units": "kilometers"})

    pts = [locations["office"], locations["ub_city"]]
    m = stadia(handler).compute(pts, pts, "motor_scooter")
    assert m.get("office", "ub_city").status is ElementStatus.NO_ROUTE
    assert m.cost("office", "ub_city") is None and m.cost("ub_city", "office") is not None


def test_locations_beyond_200km_are_refused_before_any_request(locations):
    from routewise_spike.models import Location

    called = []
    far = Location("mysuru_far", "synthetic far point", 12.2958, 76.6394)
    chennai = Location("chennai_far", "synthetic far point", 13.0827, 80.2707)
    with pytest.raises(ProviderRequestTooLarge):
        stadia(lambda r: called.append(r)).compute([far, chennai], [far, chennai], "motor_scooter")
    assert called == []


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(400, json={"error": "no suitable edges near location"}), ProviderRequestRejected),
        (httpx.Response(401, json={}), ProviderAuthError),
        (httpx.Response(403, json={}), ProviderAuthError),  # also: plan without the matrix API
        (httpx.Response(429, json={}), ProviderRateLimited),
        (httpx.Response(504, text="gateway timeout"), ProviderTimeout),
        (httpx.Response(500, text="oops"), ProviderUnavailable),
        (httpx.Response(200, text="not json"), ProviderMalformedResponse),
        (httpx.Response(200, json={"units": "kilometers"}), ProviderMalformedResponse),
        (httpx.Response(200, json={"sources_to_targets": cells(2, 2), "units": "miles"}), ProviderMalformedResponse),
        (httpx.Response(200, json={"sources_to_targets": cells(1, 2), "units": "kilometers"}), ProviderMalformedResponse),
        (httpx.Response(200, json={"sources_to_targets": [[{"from_index": 0, "to_index": 0, "distance": 0, "time": 0}] * 2] * 2,
                                   "units": "kilometers"}), ProviderMalformedResponse),
        (httpx.Response(200, json={"sources_to_targets": [[{"from_index": 0, "to_index": j, "distance": 1.0, "time": None}
                                                           for j in range(2)], cells(2, 2)[1]], "units": "kilometers"}),
         ProviderMalformedResponse),
        (httpx.Response(200, json={"sources_to_targets": [[{"from_index": 0, "to_index": j, "distance": "1", "time": 5}
                                                           for j in range(2)], cells(2, 2)[1]], "units": "kilometers"}),
         ProviderMalformedResponse),
    ],
    ids=["400-unroutable", "401", "403-plan", "429", "504", "500", "non-json", "missing-matrix", "wrong-units",
         "row-mismatch", "duplicate-cell", "half-null", "non-numeric"],
)
def test_failures_are_typed_and_never_leak_the_key(locations, response, error):
    pts = [locations["office"], locations["ub_city"]]
    with pytest.raises(error) as exc:
        stadia(lambda r: response).compute(pts, pts, "motor_scooter")
    assert KEY not in str(exc.value) and "api_key" not in str(exc.value)


def test_timeout_and_missing_key(locations):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    pts = [locations["office"], locations["ub_city"]]
    with pytest.raises(ProviderTimeout) as exc:
        stadia(slow).compute(pts, pts, "motor_scooter")
    assert KEY not in str(exc.value)
    with pytest.raises(ProviderAuthError):
        StadiaMatrixProvider("")


def test_planner_runs_on_stadia_shaped_matrix(make_round):
    """End-to-end wiring only: mocked values, so the plan is NOT a road result to report."""
    plan = optimize_round(make_round(mode=DistributionMode.SMART), stadia(ok), profile="motor_scooter")
    assert sorted(plan.assignments) == [f"O{i:02d}" for i in range(1, 13)]
    assert plan.provenance["provider"].startswith("stadia-matrix")
