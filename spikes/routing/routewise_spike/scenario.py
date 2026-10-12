"""The Phase 0 synthetic round built on public test points."""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    DeliveryRound,
    Depots,
    DistributionMode,
    Endpoint,
    EndpointKind,
    Location,
    Order,
    Rider,
    StartKind,
    Vehicle,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
LOCATIONS_FILE = FIXTURES / "public_locations_bengaluru.json"
RECORDED_OSRM = FIXTURES / "recorded" / "osrm_bengaluru_car.json"

# (order id, location id, building id) — O02/O03 share one validated entrance.
ORDERS = [
    ("O01", "cubbon_park", None),
    ("O02", "ub_city", "B-UBCITY"),
    ("O03", "ub_city", "B-UBCITY"),
    ("O04", "mg_road_metro", None),
    ("O05", "commercial_street", None),
    ("O06", "bangalore_palace", None),
    ("O07", "mantri_square", None),
    ("O08", "jayanagar_4th_block", None),
    ("O09", "forum_koramangala", None),
    ("O10", "ulsoor_lake", None),
    ("O11", "bull_temple", None),
    ("O12", "shivajinagar_bus", None),
]


def load_locations(path: Path = LOCATIONS_FILE) -> dict[str, Location]:
    data = json.loads(Path(path).read_text())
    return {d["id"]: Location(**d) for d in data["locations"]}


def phase0_round(
    locations: dict[str, Location] | None = None,
    mode: DistributionMode = DistributionMode.SMART,
    confirmed: bool = True,
) -> DeliveryRound:
    """Three riders, two starts, three different endpoint types, 12 orders."""
    locations = locations or load_locations()
    riders = [
        Rider("R1", Vehicle.SCOOTER, 5, StartKind.OFFICE, Endpoint(EndpointKind.HOME, "home_r1", confirmed)),
        Rider("R2", Vehicle.BIKE, 5, StartKind.WAREHOUSE, Endpoint(EndpointKind.CUSTOM, "custom_r2", confirmed)),
        Rider("R3", Vehicle.SCOOTER, 4, StartKind.WAREHOUSE, Endpoint(EndpointKind.LAST_STOP, None, confirmed)),
    ]
    orders = [Order(oid, loc, bld) for oid, loc, bld in ORDERS]
    return DeliveryRound(
        id="phase0-demo",
        depots=Depots("office", "warehouse"),
        riders=riders,
        orders=orders,
        locations=locations,
        mode=mode,
    )
