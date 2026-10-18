"""Self-hosted Valhalla matrix adapter (OpenStreetMap data, ODbL), in-process only.

Ported from spikes/routing/routewise_spike/matrix/valhalla_local.py at 2a34226 (accepted
Phase 0), with the matrix parser (shared with the inactive Stadia adapter in the spike) inlined.
Valhalla runs inside the API process through pyvalhalla's `Actor`: no server, no network, no
paid or public service. Two-wheeler costings only: `motor_scooter` and `motorcycle` (BETA
upstream). Never bicycle, auto or straight-line distances.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..domain import Location
from .base import (
    ElementStatus,
    MatrixElement,
    Provenance,
    ProviderMalformedResponse,
    ProviderRequestTooLarge,
    ProviderUnavailable,
    RoadMatrix,
)

COSTINGS = {"motor_scooter", "motorcycle"}
ATTRIBUTION = "Road data © OpenStreetMap contributors, ODbL 1.0. Routing by Valhalla (MIT)."


def parse_matrix(payload, origins: list[Location], destinations: list[Location]) -> dict[tuple[str, str], MatrixElement]:
    """Row-ordered `sources_to_targets` cells; distance (km) and time (s) are both null when no
    road route exists. Anything malformed raises; nothing is ever defaulted to zero."""
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


class ValhallaLocalProvider:
    name = "valhalla-local"

    def __init__(self, tile_dir: Path | str, *, max_locations: int, actor=None, data_note: str = ""):
        if actor is None:
            try:
                from valhalla import Actor, get_config
            except ImportError as exc:  # pragma: no cover - the API lock installs pyvalhalla
                raise ProviderUnavailable("pyvalhalla is not installed in this environment") from exc

            tile_dir = Path(tile_dir)
            if not tile_dir.is_dir():
                raise ProviderUnavailable(
                    f"Valhalla tiles not found at {tile_dir}; build them with spikes/valhalla/build_tiles.sh "
                    "or set ROUTEWISE_VALHALLA_TILES")
            tar = Path(str(tile_dir) + ".tar")
            # get_config resolves paths strictly; pass "" to use the tile directory alone.
            config = get_config(tile_extract=str(tar) if tar.exists() else "", tile_dir=str(tile_dir))
            for costing in COSTINGS:
                config.setdefault("service_limits", {}).setdefault(costing, {})[
                    "max_matrix_location_pairs"] = max_locations * max_locations
            actor = Actor(config)
        self._actor = actor
        self._lock = threading.Lock()  # one in-process Actor, used by one thread at a time
        self.max_locations = max_locations
        self.data_note = data_note
        self.last_latency_ms: int | None = None

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        if profile not in COSTINGS:
            raise ValueError(f"unsupported Valhalla costing {profile!r}; use motor_scooter or motorcycle")
        if len(origins) > self.max_locations or len(destinations) > self.max_locations:
            raise ProviderRequestTooLarge("matrix larger than the configured local limit")
        query = {
            "sources": [{"lat": o.lat, "lon": o.lng} for o in origins],
            "targets": [{"lat": d.lat, "lon": d.lng} for d in destinations],
            "costing": profile,
            "units": "kilometers",
        }
        requested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.monotonic()
        try:
            with self._lock:
                raw = self._actor.matrix(json.dumps(query))
        except Exception as exc:  # ValhallaError and friends: e.g. no edge near a location
            raise ProviderUnavailable(f"Valhalla matrix failed: {type(exc).__name__}") from exc
        self.last_latency_ms = round((time.monotonic() - t0) * 1000)
        try:
            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except ValueError as exc:
            raise ProviderMalformedResponse("Valhalla returned non-JSON") from exc
        elements = parse_matrix(payload, origins, destinations)
        return RoadMatrix(
            elements,
            Provenance(
                provider="valhalla-local (OpenStreetMap data)",
                real_road=True,
                profile=profile,
                requested_at=requested_at,
                element_count=len(origins) * len(destinations),
                response_status=f"in-process Actor OK, {self.last_latency_ms} ms",
                notes=f"{ATTRIBUTION} {self.data_note}".strip(),
            ),
        )

    def snap_distances_m(self, points: list[Location], profile: str) -> dict[str, float | None]:
        """Distance from each point to the road edge Valhalla would use (measurement only)."""
        query = {"locations": [{"lat": p.lat, "lon": p.lng} for p in points], "costing": profile, "verbose": True}
        with self._lock:
            raw = self._actor.locate(json.dumps(query))
        result = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        out: dict[str, float | None] = {}
        for p, loc in zip(points, result):
            edges = loc.get("edges") or []
            out[p.id] = min((e["distance"] for e in edges if "distance" in e), default=None)
        return out


__all__ = ["ValhallaLocalProvider", "parse_matrix", "ATTRIBUTION", "COSTINGS"]
