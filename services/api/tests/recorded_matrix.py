"""Test-only matrix provider: replays the recorded real local-Valhalla matrices for the public
DU North Campus points (tests/fixtures/recorded/valhalla_du_north_{motor_scooter,motorcycle}.json).

Points are matched by exact coordinates, so planner location ids can be anything. A point that
is not in the recording raises ProviderUnavailable (never a guessed or straight-line cost).
Injected through `app.state.planning.provider_override`; it cannot be selected by configuration.
"""

from __future__ import annotations

import json

from routewise_api.config import REPO_ROOT
from routewise_api.routing.matrix.base import (
    ElementStatus,
    MatrixElement,
    Provenance,
    ProviderUnavailable,
    RoadMatrix,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures"
PUBLIC_DU = {p["id"]: p for p in json.loads((FIXTURES / "public_locations_du_north.json").read_text())["locations"]}


def _load(profile: str):
    data = json.loads((FIXTURES / "recorded" / f"valhalla_du_north_{profile}.json").read_text())
    elements = {}
    for o, d, status, dist, dur in data["elements"]:
        st = ElementStatus(status)
        elements[(o, d)] = MatrixElement(st, dist, dur) if st is ElementStatus.OK else MatrixElement(st)
    by_coord = {(loc["lat"], loc["lng"]): loc["id"] for loc in data["locations"]}
    return data["meta"], elements, by_coord


RECORDINGS = {p: _load(p) for p in ("motor_scooter", "motorcycle")}


class RecordedDUProvider:
    """`missing` holds (from fixture id, to fixture id, profile or None) arcs to report as NO_ROUTE."""

    name = "valhalla-local (recorded)"

    def __init__(self, *, missing=(), fail: bool = False, synthetic: bool = False):
        self.missing = set(missing)
        self.fail = fail
        self.synthetic = synthetic
        self.calls: list[tuple[str, int]] = []

    def fixture_id(self, loc) -> str:
        meta, elements, by_coord = RECORDINGS["motor_scooter"]
        fid = by_coord.get((loc.lat, loc.lng))
        if fid is None:
            raise ProviderUnavailable("point is not part of the recording")
        return fid

    def element(self, profile: str, a: str, b: str) -> MatrixElement:
        if a == b:
            return MatrixElement(ElementStatus.OK, 0, 0)
        if (a, b, None) in self.missing or (a, b, profile) in self.missing:
            return MatrixElement(ElementStatus.NO_ROUTE)
        return RECORDINGS[profile][1][(a, b)]

    def compute(self, origins, destinations, profile) -> RoadMatrix:
        if self.fail:
            raise ProviderUnavailable("simulated routing engine failure")
        self.calls.append((profile, len(origins)))
        meta = RECORDINGS[profile][0]
        elements = {(o.id, d.id): self.element(profile, self.fixture_id(o), self.fixture_id(d))
                    for o in origins for d in destinations if o.id != d.id}
        return RoadMatrix(elements, Provenance(
            provider="SYNTHETIC test matrix" if self.synthetic else meta["provider"],
            real_road=not self.synthetic and bool(meta["real_road"]), profile=meta["profile"],
            requested_at=meta["requested_at"], element_count=len(origins) * len(destinations),
            response_status=meta.get("response_status", ""), recorded=True, notes=meta.get("notes", "")))
