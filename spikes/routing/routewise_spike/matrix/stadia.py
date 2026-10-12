"""Stadia Maps Time/Distance Matrix adapter (hosted Valhalla on OSM data).

Contract taken from Stadia's published OpenAPI spec (api.stadiamaps.com/openapi.yaml,
version 11.1.0, read 2026-10-12):
- POST https://api.stadiamaps.com/matrix/v1, API key as the `api_key` query parameter
- request: sources[], targets[] ({lat, lon}), costing, optional costing_options, units
- `matrixCostingModel` enum includes `motor_scooter` and `motorcycle`
- response: sources_to_targets (row-ordered) of {from_index, to_index, distance, time};
  distance/time are null when no route was found; `units` is kilometers|miles
- HTTP 400 when no suitable road edge is found near a location

Plan limits (pricing page + docs/limits, read 2026-10-12): the matrix is NOT available on
Free or Starter; Standard allows 625 elements per request, Professional 10,000. Max 200 km
straight-line distance between all locations for non-automobile modes.

Terms (§8): server-side caching of results is prohibited and benchmarking against
competitor services needs written permission. This adapter therefore returns values for
in-memory use only and never records raw responses.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx

from ..models import Location
from .base import (
    ElementStatus,
    MatrixElement,
    Provenance,
    ProviderAuthError,
    ProviderError,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderRequestTooLarge,
    ProviderTimeout,
    ProviderUnavailable,
    RoadMatrix,
)

ENDPOINT = "https://api.stadiamaps.com/matrix/v1"
COSTINGS = {"motor_scooter", "motorcycle"}  # two-wheeler profiles only; never bicycle
STANDARD_MAX_ELEMENTS = 625
MAX_BLINE_KM = 200.0  # "All others" (non-automobile) limit


class ProviderRequestRejected(ProviderError):
    """HTTP 400, e.g. a location with no suitable road edge nearby. Ask for a better pin."""


def _bline_km(a: Location, b: Location) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


class StadiaMatrixProvider:
    name = "stadia-matrix"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout_s: float = 30.0,
        max_elements: int = STANDARD_MAX_ELEMENTS,
        costing_options: dict | None = None,
    ):
        if not api_key:
            raise ProviderAuthError("STADIA_API_KEY is not set")
        self._key = api_key
        # Note for Phase 1: httpx logs request URLs at INFO, and the key is a query
        # parameter here, so keep the "httpx" logger at WARNING or redact it.
        self._client = client or httpx.Client(timeout=timeout_s)
        self.max_elements = max_elements
        self.tile = int(math.isqrt(max_elements))
        self.costing_options = costing_options or {}
        self.requests_made = 0

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        if profile not in COSTINGS:
            raise ValueError(f"unsupported Stadia costing {profile!r}; use motor_scooter or motorcycle")
        everything = {loc.id: loc for loc in [*origins, *destinations]}.values()
        widest = max((_bline_km(a, b) for a in everything for b in everything), default=0.0)
        if widest > MAX_BLINE_KM:
            raise ProviderRequestTooLarge(f"locations span {widest:.0f} km; Stadia limit is {MAX_BLINE_KM:.0f} km")
        requested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        elements: dict[tuple[str, str], MatrixElement] = {}
        batches = 0
        for oi in range(0, len(origins), self.tile):
            for di in range(0, len(destinations), self.tile):
                elements.update(self._request(origins[oi : oi + self.tile], destinations[di : di + self.tile], profile))
                batches += 1
        return RoadMatrix(
            elements,
            Provenance(
                provider="stadia-matrix (Valhalla, OpenStreetMap data)",
                real_road=True,
                profile=profile,
                requested_at=requested_at,
                element_count=len(origins) * len(destinations),
                response_status=f"{batches} batch(es) HTTP 200",
                notes="transient use only: Stadia ToS §8 prohibits server-side caching; do not persist raw values",
            ),
        )

    def _request(self, origins: list[Location], destinations: list[Location], costing: str):
        if len(origins) * len(destinations) > self.max_elements:
            raise ProviderRequestTooLarge("batch exceeds the plan's element limit")
        body = {
            "sources": [{"lat": o.lat, "lon": o.lng} for o in origins],
            "targets": [{"lat": d.lat, "lon": d.lng} for d in destinations],
            "costing": costing,
            "units": "km",
        }
        if self.costing_options:
            body["costing_options"] = {costing: self.costing_options}
        try:
            resp = self._client.post(ENDPOINT, params={"api_key": self._key}, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Stadia matrix timed out: {type(exc).__name__}") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"Stadia matrix unreachable: {type(exc).__name__}") from exc
        self.requests_made += 1
        # Messages carry the status code only: never the URL (it contains the key) or body.
        if resp.status_code == 400:
            raise ProviderRequestRejected("Stadia HTTP 400: a location may have no routable road nearby")
        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"Stadia HTTP {resp.status_code}: invalid key or plan lacks the matrix API")
        if resp.status_code == 429:
            raise ProviderRateLimited("Stadia HTTP 429")
        if resp.status_code == 504:
            raise ProviderTimeout("Stadia HTTP 504")
        if resp.status_code != 200:
            raise ProviderUnavailable(f"Stadia HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderMalformedResponse("Stadia response is not JSON") from exc
        return self._parse(payload, origins, destinations)

    @staticmethod
    def _parse(payload, origins: list[Location], destinations: list[Location]):
        if not isinstance(payload, dict) or not isinstance(payload.get("sources_to_targets"), list):
            raise ProviderMalformedResponse("missing sources_to_targets")
        if payload.get("units") != "kilometers":
            raise ProviderMalformedResponse(f"unexpected units {payload.get('units')!r}")
        rows = payload["sources_to_targets"]
        if len(rows) != len(origins):
            raise ProviderMalformedResponse("row count mismatch")
        out: dict[tuple[str, str], MatrixElement] = {}
        for row in rows:
            if not isinstance(row, list) or len(row) != len(destinations):
                raise ProviderMalformedResponse("column count mismatch")
            for cell in row:
                if not isinstance(cell, dict):
                    raise ProviderMalformedResponse("matrix cell is not an object")
                fi, ti = cell.get("from_index"), cell.get("to_index")
                if not (isinstance(fi, int) and isinstance(ti, int)
                        and 0 <= fi < len(origins) and 0 <= ti < len(destinations)):
                    raise ProviderMalformedResponse("bad from_index/to_index")
                key = (origins[fi].id, destinations[ti].id)
                if key in out:
                    raise ProviderMalformedResponse("duplicate matrix cell")
                dist, secs = cell.get("distance"), cell.get("time")
                if dist is None or secs is None:
                    if dist is not None or secs is not None:
                        raise ProviderMalformedResponse("only one of distance/time is null")
                    out[key] = MatrixElement(ElementStatus.NO_ROUTE)
                elif isinstance(dist, (int, float)) and isinstance(secs, int) and not isinstance(secs, bool):
                    out[key] = MatrixElement(ElementStatus.OK, round(dist * 1000), secs)
                else:
                    raise ProviderMalformedResponse("non-numeric distance/time")
        if len(out) != len(origins) * len(destinations):
            raise ProviderMalformedResponse("incomplete matrix")
        return out
