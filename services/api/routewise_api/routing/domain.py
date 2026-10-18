"""Routing domain model used by the planner (in-memory; not the database schema).

Ported from spikes/routing/routewise_spike/models.py at 2a34226 (accepted Phase 0). Keep behaviour
in step with the spike; parity is tested in tests/test_routing_parity.py.

Only what the spike needs. Statuses are exactly Pending / Postponed / Completed;
"waiting to sync" and similar markers are metadata, never a status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "Pending"
    POSTPONED = "Postponed"
    COMPLETED = "Completed"


class StartKind(str, Enum):
    OFFICE = "office"
    WAREHOUSE = "warehouse"


class EndpointKind(str, Enum):
    OFFICE = "office"
    WAREHOUSE = "warehouse"
    HOME = "home"
    LAST_STOP = "last_stop"
    CUSTOM = "custom"


class Vehicle(str, Enum):
    SCOOTER = "scooter"
    BIKE = "bike"  # motorbike; never routed with a bicycle profile


class DistributionMode(str, Enum):
    EQUAL = "equal"
    SMART = "smart"
    MANUAL = "manual"


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    lat: float
    lng: float


@dataclass
class Order:
    id: str
    location_id: str | None  # None = unresolved pin; blocks planning
    building_id: str | None = None  # validated shared entrance, not mere proximity
    status: OrderStatus = OrderStatus.PENDING
    locked_rider_id: str | None = None  # manual ownership lock
    first_priority: bool = False
    completed_at: str | None = None  # ISO timestamp, used for "last completed stop"


@dataclass
class Endpoint:
    kind: EndpointKind
    location_id: str | None = None  # required for HOME / CUSTOM
    confirmed: bool = False


@dataclass
class Rider:
    id: str
    vehicle: Vehicle
    capacity: int  # counted in orders (D06)
    start: StartKind
    endpoint: Endpoint | None = None
    active: bool = True  # removed riders do not count toward the confirmation gate


@dataclass
class Depots:
    office_location_id: str
    warehouse_location_id: str


@dataclass
class DeliveryRound:
    id: str
    depots: Depots
    riders: list[Rider]
    orders: list[Order]
    locations: dict[str, Location]
    mode: DistributionMode = DistributionMode.SMART

    def rider(self, rider_id: str) -> Rider:
        for r in self.riders:
            if r.id == rider_id:
                return r
        raise KeyError(rider_id)

    def order(self, order_id: str) -> Order:
        for o in self.orders:
            if o.id == order_id:
                return o
        raise KeyError(order_id)

    def active_riders(self) -> list[Rider]:
        return [r for r in self.riders if r.active]

    def start_location_id(self, rider: Rider) -> str:
        if rider.start is StartKind.OFFICE:
            return self.depots.office_location_id
        return self.depots.warehouse_location_id

    def end_location_id(self, endpoint: Endpoint) -> str | None:
        """Fixed end location, or None for an open (Last stop) route."""
        if endpoint.kind is EndpointKind.OFFICE:
            return self.depots.office_location_id
        if endpoint.kind is EndpointKind.WAREHOUSE:
            return self.depots.warehouse_location_id
        if endpoint.kind is EndpointKind.LAST_STOP:
            return None
        return endpoint.location_id


@dataclass
class Stop:
    """A navigation stop. One stop may carry several independent orders."""

    location_id: str
    order_ids: list[str]
    building_id: str | None = None


@dataclass
class RiderRoute:
    rider_id: str
    version: int
    start_location_id: str
    endpoint_kind: EndpointKind
    end_location_id: str | None  # None = open route ending at the last delivery
    stops: list[Stop]
    road_distance_m: int  # real matrix edges only; virtual Last-stop sink excluded
    road_duration_s: int
    origin_kind: str = "configured_start"  # or current_position / last_completed_stop / confirmed_pin
    origin_label: str = ""
    postponed_order_ids: list[str] = field(default_factory=list)
    completed_order_ids: list[str] = field(default_factory=list)

    def order_ids(self) -> list[str]:
        return [oid for s in self.stops for oid in s.order_ids]


@dataclass
class Plan:
    round_id: str
    version: int
    input_fingerprint: str
    mode: DistributionMode
    routes: dict[str, RiderRoute]
    assignments: dict[str, str]  # order id -> rider id (exactly one owner)
    distance_label: str
    provenance: dict
    warnings: list[str] = field(default_factory=list)
