"""OSRM Table service adapter (OpenStreetMap road network).

Used in Phase 0 as a credential-free source of *real* road distances. The public
demo server (router.project-osrm.org) is limited to reasonable non-commercial
use at <= 1 request/second with no uptime guarantee, so it is research evidence
only and never a production dependency. Its car profile is a proxy: it is not a
motorized two-wheeler profile. Data © OpenStreetMap contributors (ODbL).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from ..models import Location
from .base import (
    ElementStatus,
    MatrixElement,
    Provenance,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderRequestTooLarge,
    ProviderTimeout,
    ProviderUnavailable,
    RoadMatrix,
)

DEMO_BASE_URL = "https://router.project-osrm.org"
USER_AGENT = "RouteWise-Phase0-spike/0.1 (local research; low volume)"
PROFILES = {"car_proxy": "driving"}


class OSRMTableProvider:
    name = "osrm-table"

    def __init__(
        self,
        base_url: str = DEMO_BASE_URL,
        client: httpx.Client | None = None,
        timeout_s: float = 20.0,
        min_interval_s: float = 1.1,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s, headers={"User-Agent": USER_AGENT})
        self._min_interval = min_interval_s
        self._last_call = 0.0
        self.last_raw: dict | None = None  # kept so the CLI can record evidence
        self.last_url: str | None = None

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        if profile not in PROFILES:
            raise ValueError(f"unsupported OSRM profile {profile!r}")
        # One combined coordinate list; sources/destinations index into it.
        coords: list[Location] = []
        index: dict[str, int] = {}
        for loc in [*origins, *destinations]:
            if loc.id not in index:
                index[loc.id] = len(coords)
                coords.append(loc)
        coord_str = ";".join(f"{c.lng:.6f},{c.lat:.6f}" for c in coords)
        params = {
            "annotations": "distance,duration",
            "sources": ";".join(str(index[o.id]) for o in origins),
            "destinations": ";".join(str(index[d.id]) for d in destinations),
        }
        url = f"{self.base_url}/table/v1/{PROFILES[profile]}/{coord_str}"
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        requested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            resp = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"OSRM timed out: {type(exc).__name__}") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"OSRM unreachable: {type(exc).__name__}") from exc
        finally:
            self._last_call = time.monotonic()
        if resp.status_code == 429:
            raise ProviderRateLimited("OSRM HTTP 429")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderMalformedResponse(f"OSRM HTTP {resp.status_code}: non-JSON body") from exc
        self.last_raw, self.last_url = payload, str(resp.request.url)
        return parse_table(payload, origins, destinations, requested_at, http_status=resp.status_code)


def parse_table(
    payload,
    origins: list[Location],
    destinations: list[Location],
    requested_at: str,
    http_status: int = 200,
    recorded: bool = False,
) -> RoadMatrix:
    if not isinstance(payload, dict):
        raise ProviderMalformedResponse("OSRM response is not an object")
    code = payload.get("code")
    if code == "TooBig":
        raise ProviderRequestTooLarge("OSRM TooBig")
    if code != "Ok" or http_status != 200:
        raise ProviderUnavailable(f"OSRM HTTP {http_status} code {code!r}")
    dist, dur = payload.get("distances"), payload.get("durations")
    if not (isinstance(dist, list) and isinstance(dur, list)):
        raise ProviderMalformedResponse("missing distances/durations")
    if len(dist) != len(origins) or len(dur) != len(origins):
        raise ProviderMalformedResponse("row count mismatch")
    elements: dict[tuple[str, str], MatrixElement] = {}
    for i, o in enumerate(origins):
        if len(dist[i]) != len(destinations) or len(dur[i]) != len(destinations):
            raise ProviderMalformedResponse("column count mismatch")
        for j, d in enumerate(destinations):
            dm, ds = dist[i][j], dur[i][j]
            if dm is None or ds is None:  # OSRM uses null for "no route"
                elements[(o.id, d.id)] = MatrixElement(ElementStatus.NO_ROUTE)
            elif isinstance(dm, (int, float)) and isinstance(ds, (int, float)):
                elements[(o.id, d.id)] = MatrixElement(ElementStatus.OK, round(dm), round(ds))
            else:
                raise ProviderMalformedResponse("non-numeric matrix value")
    snaps = [w.get("distance") for w in payload.get("sources", []) if isinstance(w, dict)]
    return RoadMatrix(
        elements,
        Provenance(
            provider="osrm-table (OpenStreetMap data)",
            real_road=True,
            profile="car (proxy; not a two-wheeler profile)",
            requested_at=requested_at,
            element_count=len(origins) * len(destinations),
            response_status=f"HTTP {http_status} code {code}",
            recorded=recorded,
            notes=f"max snap distance {max(snaps):.0f} m" if snaps else "",
        ),
    )
