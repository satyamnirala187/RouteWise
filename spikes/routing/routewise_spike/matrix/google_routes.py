"""Google Routes API Compute Route Matrix adapter.

Reference (checked 2026-10-12):
https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRouteMatrix
- POST https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix
- origins x destinations <= 625 per request (100 with TRAFFIC_AWARE_OPTIMAL)
- field mask must include `status`, otherwise every element looks OK
- proto3 JSON omits zero values, so originIndex/destinationIndex/distanceMeters
  can be absent when 0
- TWO_WHEELER bills at the Enterprise SKU; never used without explicit approval
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from ..models import Location
from .base import (
    ElementStatus,
    MatrixElement,
    Provenance,
    ProviderAuthError,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderRequestTooLarge,
    ProviderTimeout,
    ProviderUnavailable,
    RoadMatrix,
)

ENDPOINT = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
FIELD_MASK = "originIndex,destinationIndex,status,condition,distanceMeters,duration"
MAX_ELEMENTS_PER_REQUEST = 625
TILE = 25  # 25 x 25 = 625

TRAVEL_MODES = {"two_wheeler": "TWO_WHEELER", "drive": "DRIVE"}
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)s$")


def _waypoint(loc: Location) -> dict:
    return {"waypoint": {"location": {"latLng": {"latitude": loc.lat, "longitude": loc.lng}}}}


class GoogleRoutesMatrixProvider:
    name = "google-routes-computeRouteMatrix"

    def __init__(self, api_key: str, client: httpx.Client | None = None, timeout_s: float = 20.0):
        if not api_key:
            raise ProviderAuthError("GOOGLE_MAPS_API_KEY is not set")
        self._key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        if profile not in TRAVEL_MODES:
            raise ValueError(f"unsupported profile {profile!r}; bicycle routing is never used")
        elements: dict[tuple[str, str], MatrixElement] = {}
        requests = 0
        for oi in range(0, len(origins), TILE):
            for di in range(0, len(destinations), TILE):
                o_chunk, d_chunk = origins[oi : oi + TILE], destinations[di : di + TILE]
                elements.update(self._request(o_chunk, d_chunk, TRAVEL_MODES[profile]))
                requests += 1
        return RoadMatrix(
            elements,
            Provenance(
                provider=self.name,
                real_road=True,
                profile=TRAVEL_MODES[profile],
                requested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                element_count=len(origins) * len(destinations),
                response_status=f"{requests} request(s) OK",
            ),
        )

    def _request(self, origins: list[Location], destinations: list[Location], mode: str):
        if len(origins) * len(destinations) > MAX_ELEMENTS_PER_REQUEST:
            raise ProviderRequestTooLarge("tile exceeds 625 elements")
        body = {
            "origins": [_waypoint(o) for o in origins],
            "destinations": [_waypoint(d) for d in destinations],
            "travelMode": mode,
            "routingPreference": "TRAFFIC_UNAWARE",
        }
        headers = {"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": FIELD_MASK}
        try:
            resp = self._client.post(ENDPOINT, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Routes API timed out: {type(exc).__name__}") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"Routes API unreachable: {type(exc).__name__}") from exc
        self._raise_for_status(resp)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderMalformedResponse("response is not JSON") from exc
        return self._parse(payload, origins, destinations)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code == 200:
            return
        reason = ""
        try:
            err = resp.json().get("error", {})
            reason = err.get("status", "")
            for d in err.get("details", []) or []:
                reason = d.get("reason", reason) or reason
        except (ValueError, AttributeError):
            pass
        # Never echo the key or full body; status code + reason only.
        msg = f"Routes API HTTP {resp.status_code} {reason}".strip()
        if resp.status_code == 429 or reason == "RESOURCE_EXHAUSTED":
            raise ProviderRateLimited(msg)
        if resp.status_code in (401, 403) or reason in ("API_KEY_INVALID", "PERMISSION_DENIED"):
            raise ProviderAuthError(msg)
        if resp.status_code == 504:
            raise ProviderTimeout(msg)
        raise ProviderUnavailable(msg)

    @staticmethod
    def _parse(payload, origins: list[Location], destinations: list[Location]):
        if not isinstance(payload, list):
            raise ProviderMalformedResponse("expected a JSON array of matrix elements")
        out: dict[tuple[str, str], MatrixElement] = {}
        for raw in payload:
            if not isinstance(raw, dict):
                raise ProviderMalformedResponse("matrix element is not an object")
            oi, di = raw.get("originIndex", 0), raw.get("destinationIndex", 0)
            if not (isinstance(oi, int) and isinstance(di, int)):
                raise ProviderMalformedResponse("non-integer element index")
            if not (0 <= oi < len(origins) and 0 <= di < len(destinations)):
                raise ProviderMalformedResponse("element index out of range")
            key = (origins[oi].id, destinations[di].id)
            if key in out:
                raise ProviderMalformedResponse("duplicate matrix element")
            status = raw.get("status") or {}
            if status.get("code", 0) != 0:
                out[key] = MatrixElement(ElementStatus.ERROR)
                continue
            condition = raw.get("condition")
            if condition == "ROUTE_NOT_FOUND":
                out[key] = MatrixElement(ElementStatus.NO_ROUTE)
                continue
            if condition != "ROUTE_EXISTS":
                raise ProviderMalformedResponse(f"unexpected element condition {condition!r}")
            dist = raw.get("distanceMeters", 0)
            m = _DURATION.match(str(raw.get("duration", "0s")))
            if not isinstance(dist, int) or m is None:
                raise ProviderMalformedResponse("bad distance/duration encoding")
            out[key] = MatrixElement(ElementStatus.OK, dist, round(float(m.group(1))))
        expected = len(origins) * len(destinations)
        if len(out) != expected:
            raise ProviderMalformedResponse(f"expected {expected} elements, got {len(out)}")
        return out
