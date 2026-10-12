"""Synthetic matrices for unit tests only. Always provenance real_road=False."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from ..models import Location
from .base import ElementStatus, MatrixElement, Provenance, RoadMatrix


def _haversine_m(a: Location, b: Location) -> float:
    r = 6_371_000
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class SyntheticMatrixProvider:
    """Straight-line based costs with an optional directed bias.

    unreachable: directed pairs (origin_id, destination_id) reported as NO_ROUTE.
    """

    name = "synthetic"

    def __init__(self, unreachable: set[tuple[str, str]] | None = None, asymmetry: float = 0.0):
        self.unreachable = unreachable or set()
        self.asymmetry = asymmetry

    def compute(self, origins: list[Location], destinations: list[Location], profile: str) -> RoadMatrix:
        elements = {}
        for o in origins:
            for d in destinations:
                if (o.id, d.id) in self.unreachable:
                    elements[(o.id, d.id)] = MatrixElement(ElementStatus.NO_ROUTE)
                    continue
                base = _haversine_m(o, d) * 1.3
                bias = 1 + self.asymmetry if o.id < d.id else 1.0
                dist = round(base * bias)
                elements[(o.id, d.id)] = MatrixElement(ElementStatus.OK, dist, round(dist / 6.0))
        return RoadMatrix(
            elements,
            Provenance(
                provider="synthetic straight-line x1.3",
                real_road=False,
                profile=f"synthetic ({profile})",
                requested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                element_count=len(elements),
                response_status="synthetic",
                notes="unit-test fixture; not road distances",
            ),
        )
