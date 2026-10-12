"""Self-hosted Valhalla matrix adapter (OpenStreetMap data, ODbL).

Runs Valhalla in-process through pyvalhalla's `Actor` (no server, no network), or
against a self-hosted `valhalla_service` over HTTP. Two-wheeler costings only:
`motor_scooter` (mopeds/scooters) and `motorcycle` (BETA upstream). Never bicycle.

Valhalla's matrix response is the same shape Stadia documents: row-ordered
`sources_to_targets` cells with `distance` (in `units`) and `time` (s), both null
when no route exists, so the parser is shared with the Stadia adapter.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..models import Location
from .base import (
    MatrixElement,
    Provenance,
    ProviderError,
    ProviderMalformedResponse,
    ProviderRequestTooLarge,
    ProviderUnavailable,
    RoadMatrix,
)
from .stadia import StadiaMatrixProvider

COSTINGS = {"motor_scooter", "motorcycle"}
ATTRIBUTION = "Road data © OpenStreetMap contributors, ODbL 1.0. Routing by Valhalla (MIT)."


class ValhallaLocalProvider:
    name = "valhalla-local"

    def __init__(self, tile_dir: Path | str, *, max_locations: int = 200, actor=None, data_note: str = ""):
        if actor is None:
            from valhalla import Actor, get_config  # optional dependency (.venv-valhalla)

            tile_dir = Path(tile_dir)
            if not tile_dir.is_dir():
                raise ProviderUnavailable(f"Valhalla tiles not found at {tile_dir}; run spikes/valhalla/build_tiles.sh")
            tar = Path(str(tile_dir) + ".tar")
            # get_config resolves paths strictly; pass "" to use the tile directory alone.
            config = get_config(tile_extract=str(tar) if tar.exists() else "", tile_dir=str(tile_dir))
            # The default service limits are conservative; the matrix here is small and local.
            for costing in ("motor_scooter", "motorcycle"):
                config.setdefault("service_limits", {}).setdefault(costing, {})["max_matrix_location_pairs"] = 2500
            actor = Actor(config)
        self._actor = actor
        self.max_locations = max_locations
        self.data_note = data_note
        self.last_latency_ms: int | None = None

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        if profile not in COSTINGS:
            raise ValueError(f"unsupported Valhalla costing {profile!r}; use motor_scooter or motorcycle")
        if len(origins) * len(destinations) > self.max_locations**2:
            raise ProviderRequestTooLarge("matrix larger than configured local limit")
        query = {
            "sources": [{"lat": o.lat, "lon": o.lng} for o in origins],
            "targets": [{"lat": d.lat, "lon": d.lng} for d in destinations],
            "costing": profile,
            "units": "kilometers",
        }
        requested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.monotonic()
        try:
            raw = self._actor.matrix(json.dumps(query))
        except Exception as exc:  # ValhallaError and friends: e.g. no edge near a location
            raise ProviderUnavailable(f"Valhalla matrix failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        self.last_latency_ms = round((time.monotonic() - t0) * 1000)
        try:
            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except ValueError as exc:
            raise ProviderMalformedResponse("Valhalla returned non-JSON") from exc
        elements: dict[tuple[str, str], MatrixElement] = StadiaMatrixProvider._parse(payload, origins, destinations)
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


def to_recording(matrix: RoadMatrix, locations: list[Location], meta: dict) -> dict:
    """Normalised, provider-neutral recording of a real matrix (ODbL data may be stored)."""
    ids = [loc.id for loc in locations]
    return {
        "meta": matrix.provenance.as_dict() | meta,
        "locations": [loc.__dict__ for loc in locations],
        "elements": [
            [o, d, matrix.get(o, d).status.value, matrix.get(o, d).distance_m, matrix.get(o, d).duration_s]
            for o in ids for d in ids if o != d
        ],
    }


__all__ = ["ValhallaLocalProvider", "to_recording", "ATTRIBUTION", "ProviderError"]
