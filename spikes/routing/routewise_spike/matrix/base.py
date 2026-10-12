"""Provider-neutral road matrix types and errors.

A missing or failed element is never converted into a zero-cost edge, and
non-road (synthetic) matrices are always labelled as such via provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from ..models import Location


class ElementStatus(str, Enum):
    OK = "ok"
    NO_ROUTE = "no_route"  # provider says no road route exists
    ERROR = "error"  # provider returned an element-level error


@dataclass(frozen=True)
class MatrixElement:
    status: ElementStatus
    distance_m: int | None = None
    duration_s: int | None = None

    def __post_init__(self) -> None:
        if self.status is ElementStatus.OK:
            if self.distance_m is None or self.duration_s is None:
                raise ValueError("OK element needs distance and duration")
            if self.distance_m < 0 or self.duration_s < 0:
                raise ValueError("negative road cost")
        elif self.distance_m is not None or self.duration_s is not None:
            raise ValueError("failed element must not carry a cost")


@dataclass
class Provenance:
    provider: str
    real_road: bool  # True only for an actual road-network provider response
    profile: str
    requested_at: str  # ISO-8601 UTC
    units: dict = field(default_factory=lambda: {"distance": "meters", "duration": "seconds"})
    element_count: int = 0
    response_status: str = ""
    recorded: bool = False  # replayed from a captured real response
    notes: str = ""

    def label(self) -> str:
        if not self.real_road:
            return f"SYNTHETIC — NOT ROAD DISTANCES ({self.provider})"
        replay = f", recorded response captured {self.requested_at}" if self.recorded else ""
        return f"Road distances: {self.provider}, profile {self.profile}{replay}"

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "real_road": self.real_road,
            "profile": self.profile,
            "requested_at": self.requested_at,
            "units": self.units,
            "element_count": self.element_count,
            "response_status": self.response_status,
            "recorded": self.recorded,
            "notes": self.notes,
        }


@dataclass
class RoadMatrix:
    """Directed matrix keyed by (origin location id, destination location id)."""

    elements: dict[tuple[str, str], MatrixElement]
    provenance: Provenance

    def get(self, origin_id: str, destination_id: str) -> MatrixElement:
        if origin_id == destination_id:
            return MatrixElement(ElementStatus.OK, 0, 0)
        try:
            return self.elements[(origin_id, destination_id)]
        except KeyError:
            raise KeyError(f"matrix has no element {origin_id}->{destination_id}") from None

    def cost(self, origin_id: str, destination_id: str, metric: str = "distance") -> int | None:
        el = self.get(origin_id, destination_id)
        if el.status is not ElementStatus.OK:
            return None
        return el.distance_m if metric == "distance" else el.duration_s


class ProviderError(Exception):
    """Base class: the matrix request failed as a whole. Callers keep the last valid plan."""


class ProviderTimeout(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderMalformedResponse(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderRequestTooLarge(ProviderError):
    pass


class MatrixProvider(Protocol):
    name: str

    def compute(
        self, origins: list[Location], destinations: list[Location], profile: str
    ) -> RoadMatrix: ...
