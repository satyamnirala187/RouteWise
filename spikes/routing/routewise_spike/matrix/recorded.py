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
