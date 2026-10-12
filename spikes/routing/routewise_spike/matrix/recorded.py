"""Replay a captured real OSRM table response so tests are reproducible offline.

The recording is real provider output for public points; replaying it keeps
real_road=True but marks recorded=True with the original capture timestamp.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Location
from .base import Provenance, RoadMatrix
from .osrm import parse_table


class RecordedOSRMProvider:
    name = "osrm-table (recorded)"

    def __init__(self, path: Path):
        data = json.loads(Path(path).read_text())
        self.meta = data["meta"]
        locs = [Location(**loc) for loc in data["locations"]]
        self.locations = {loc.id: loc for loc in locs}
        full = parse_table(data["response"], locs, locs, self.meta["requested_at"], recorded=True)
        self._full = full

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        for loc in [*origins, *destinations]:
            rec = self.locations.get(loc.id)
            if rec is None or (rec.lat, rec.lng) != (loc.lat, loc.lng):
                raise KeyError(f"location {loc.id} is not part of the recording")
        elements = {
            (o.id, d.id): self._full.get(o.id, d.id) for o in origins for d in destinations
        }
        p = self._full.provenance
        return RoadMatrix(
            elements,
            Provenance(
                provider=p.provider,
                real_road=True,
                profile=p.profile,
                requested_at=p.requested_at,
                element_count=len(elements),
                response_status=p.response_status,
                recorded=True,
                notes=p.notes,
            ),
        )


class RecordedMatrixProvider:
    """Replay a normalised recording (see matrix.valhalla_local.to_recording)."""

    def __init__(self, path: Path):
        from .base import ElementStatus, MatrixElement

        data = json.loads(Path(path).read_text())
        self.meta = data["meta"]
        self.locations = {d["id"]: Location(**d) for d in data["locations"]}
        self._elements = {}
        for o, d, status, dist, dur in data["elements"]:
            st = ElementStatus(status)
            self._elements[(o, d)] = MatrixElement(st, dist, dur) if st is ElementStatus.OK else MatrixElement(st)
        self.name = f"{self.meta['provider']} (recorded)"

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        for loc in [*origins, *destinations]:
            rec = self.locations.get(loc.id)
            if rec is None or (rec.lat, rec.lng) != (loc.lat, loc.lng):
                raise KeyError(f"location {loc.id} is not part of the recording")
        elements = {(o.id, d.id): self._elements[(o.id, d.id)]
                    for o in origins for d in destinations if o.id != d.id}
        m = self.meta
        return RoadMatrix(
            elements,
            Provenance(
                provider=m["provider"],
                real_road=bool(m["real_road"]),
                profile=m["profile"],
                requested_at=m["requested_at"],
                element_count=len(origins) * len(destinations),
                response_status=m.get("response_status", ""),
                recorded=True,
                notes=m.get("notes", ""),
            ),
        )


class ByProfile:
    """Dispatch compute() to a provider per profile (e.g. two recorded Valhalla costings)."""

    name = "by-profile"

    def __init__(self, providers: dict):
        self.providers = providers

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        return self.providers[profile].compute(origins, destinations, profile)
