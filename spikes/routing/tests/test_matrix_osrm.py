"""Criteria 2 and 9: real recorded OSRM matrix properties, and OSRM adapter failures."""

import httpx
import pytest

from routewise_spike.matrix import (
    ElementStatus,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderRequestTooLarge,
    ProviderTimeout,
    ProviderUnavailable,
)
from routewise_spike.matrix.osrm import OSRMTableProvider
from routewise_spike.models import Location

A, B = Location("a", "A", 12.97, 77.59), Location("b", "B", 12.98, 77.60)


def osrm(handler):
    return OSRMTableProvider("https://osrm.test", client=httpx.Client(transport=httpx.MockTransport(handler)),
                             min_interval_s=0)


def test_recorded_matrix_is_real_directed_and_complete(real, locations):
    ids = list(locations)
    m = real.compute(list(locations.values()), list(locations.values()), "car_proxy")
    assert m.provenance.real_road and m.provenance.recorded
    assert m.provenance.units == {"distance": "meters", "duration": "seconds"}
    assert len(m.elements) == len(ids) ** 2 == 256
    assert all(e.status is ElementStatus.OK for e in m.elements.values())
    asym = [(a, b) for a in ids for b in ids if a < b and m.get(a, b).distance_m != m.get(b, a).distance_m]
    assert len(asym) > 0, "a real road network should show directed asymmetry"
    # A documented example from the capture: Forum Mall -> Shivajinagar differs from the reverse by > 2 km.
    assert abs(m.get("forum_koramangala", "shivajinagar_bus").distance_m
               - m.get("shivajinagar_bus", "forum_koramangala").distance_m) > 2000
    assert "Road distances" in m.provenance.label() and "recorded" in m.provenance.label()


def test_recorded_provider_refuses_points_outside_recording(real):
    with pytest.raises(KeyError):
        real.compute([Location("elsewhere", "", 1, 1)], [A], "car_proxy")


def test_null_entries_become_no_route_not_zero():
    payload = {"code": "Ok", "distances": [[0, None], [500, 0]], "durations": [[0, None], [60, 0]], "sources": []}
    m = osrm(lambda r: httpx.Response(200, json=payload)).compute([A, B], [A, B], "car_proxy")
    assert m.get("a", "b").status is ElementStatus.NO_ROUTE and m.cost("a", "b") is None
    assert m.cost("b", "a") == 500


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(429, text="slow down"), ProviderRateLimited),
        (httpx.Response(400, json={"code": "TooBig"}), ProviderRequestTooLarge),
        (httpx.Response(400, json={"code": "InvalidQuery"}), ProviderUnavailable),
        (httpx.Response(502, text="bad gateway"), ProviderMalformedResponse),
        (httpx.Response(200, json={"code": "Ok", "distances": [[0]], "durations": [[0]]}), ProviderMalformedResponse),
        (httpx.Response(200, json={"code": "Ok", "distances": [[0, "x"], [1, 0]], "durations": [[0, 1], [1, 0]]}),
         ProviderMalformedResponse),
    ],
    ids=["rate-limit", "too-big", "error-code", "non-json", "row-mismatch", "non-numeric"],
)
def test_osrm_failures_are_typed(response, error):
    with pytest.raises(error):
        osrm(lambda r: response).compute([A, B], [A, B], "car_proxy")


def test_osrm_timeout_and_unknown_profile():
    def handler(req):
        raise httpx.ConnectTimeout("no route to host", request=req)

    with pytest.raises(ProviderTimeout):
        osrm(handler).compute([A, B], [A, B], "car_proxy")
    with pytest.raises(ValueError):
        osrm(handler).compute([A, B], [A, B], "bicycle")
