"""Criterion 9: provider failure handling around the actual Google Routes adapter (mocked HTTP)."""

import json

import httpx
import pytest

from routewise_spike.matrix import (
    ElementStatus,
    ProviderAuthError,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from routewise_spike.matrix.google_routes import FIELD_MASK, GoogleRoutesMatrixProvider
from routewise_spike.models import Location

KEY = "test-key-not-real"
A, B = Location("a", "A", 12.97, 77.59), Location("b", "B", 12.98, 77.60)


def provider(handler):
    return GoogleRoutesMatrixProvider(KEY, client=httpx.Client(transport=httpx.MockTransport(handler)))


def ok_elements(n_o, n_d):
    out = []
    for i in range(n_o):
        for j in range(n_d):
            el = {"status": {}, "condition": "ROUTE_EXISTS", "duration": f"{10 * (i + j)}s"}
            if i:  # proto3 JSON omits zero-valued fields
                el["originIndex"] = i
            if j:
                el["destinationIndex"] = j
            if i != j:
                el["distanceMeters"] = 1000 + 100 * i + j
            out.append(el)
    return out


def test_parses_elements_including_omitted_zero_fields_and_sends_field_mask():
    seen = {}

    def handler(req):
        seen["headers"] = req.headers
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=ok_elements(2, 2))

    m = provider(handler).compute([A, B], [A, B], "two_wheeler")
    assert seen["headers"]["x-goog-fieldmask"] == FIELD_MASK and "status" in FIELD_MASK
    assert seen["body"]["travelMode"] == "TWO_WHEELER"
    assert m.get("a", "b").distance_m == 1001 and m.get("b", "a").distance_m == 1100
    assert m.get("a", "b").duration_s == 10
    assert m.provenance.real_road and m.provenance.element_count == 4


def test_large_matrix_is_tiled_within_625_elements():
    sizes = []

    def handler(req):
        body = json.loads(req.content)
        no, nd = len(body["origins"]), len(body["destinations"])
        sizes.append(no * nd)
        return httpx.Response(200, json=ok_elements(no, nd))

    locs = [Location(f"p{i}", "", 12.9 + i / 1000, 77.5) for i in range(30)]
    m = provider(handler).compute(locs, locs, "drive")
    assert len(sizes) == 4 and max(sizes) <= 625
    assert len(m.elements) == 900


def test_route_not_found_and_element_error_are_never_zero():
    def handler(req):
        return httpx.Response(200, json=[
            {"status": {}, "condition": "ROUTE_EXISTS", "duration": "0s"},
            {"destinationIndex": 1, "status": {}, "condition": "ROUTE_NOT_FOUND"},
            {"originIndex": 1, "status": {"code": 3, "message": "bad waypoint"}},
            {"originIndex": 1, "destinationIndex": 1, "status": {}, "condition": "ROUTE_EXISTS", "duration": "0s"},
        ])

    m = provider(handler).compute([A, B], [A, B], "two_wheeler")
    assert m.get("a", "b").status is ElementStatus.NO_ROUTE and m.cost("a", "b") is None
    assert m.get("b", "a").status is ElementStatus.ERROR and m.cost("b", "a") is None


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}), ProviderRateLimited),
        (httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT",
                                              "details": [{"reason": "API_KEY_INVALID"}]}}), ProviderAuthError),
        (httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}}), ProviderAuthError),
        (httpx.Response(503, text="unavailable"), ProviderUnavailable),
        (httpx.Response(200, text="<html>not json</html>"), ProviderMalformedResponse),
        (httpx.Response(200, json={"elements": []}), ProviderMalformedResponse),
        (httpx.Response(200, json=[{"status": {}, "condition": "ROUTE_EXISTS", "duration": "1s"}]), ProviderMalformedResponse),
        (httpx.Response(200, json=ok_elements(2, 2)[:3] + [{"originIndex": 7, "condition": "ROUTE_EXISTS"}]), ProviderMalformedResponse),
        (httpx.Response(200, json=[dict(e, duration="soon") for e in ok_elements(2, 2)]), ProviderMalformedResponse),
        (httpx.Response(200, json=[dict(e, condition="MAYBE") for e in ok_elements(2, 2)]), ProviderMalformedResponse),
    ],
    ids=["rate-limit", "invalid-key", "permission", "server-error", "non-json", "not-array",
         "missing-elements", "index-out-of-range", "bad-duration", "unknown-condition"],
)
def test_http_and_payload_failures_raise_typed_errors_without_leaking_key(response, error):
    with pytest.raises(error) as exc:
        provider(lambda req: response).compute([A, B], [A, B], "two_wheeler")
    assert KEY not in str(exc.value)


def test_timeout_is_typed():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ProviderTimeout):
        provider(handler).compute([A, B], [A, B], "two_wheeler")


def test_missing_key_and_bicycle_profile_are_refused():
    with pytest.raises(ProviderAuthError):
        GoogleRoutesMatrixProvider("")
    with pytest.raises(ValueError):
        provider(lambda r: httpx.Response(200, json=[])).compute([A], [B], "bicycle")
