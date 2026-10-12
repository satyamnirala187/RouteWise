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
# Historical Phase 0 test area (Bengaluru); kept as evidence only.
LOCATIONS_FILE = FIXTURES / "public_locations_bengaluru.json"
RECORDED_OSRM = FIXTURES / "recorded" / "osrm_bengaluru_car.json"
# Confirmed delivery area: DU North Campus, Delhi (owner, 2026-10-12).
DU_LOCATIONS_FILE = FIXTURES / "public_locations_du_north.json"
RECORDED_VALHALLA = {c: FIXTURES / "recorded" / f"valhalla_du_north_{c}.json" for c in ("motor_scooter", "motorcycle")}

# (order id, location id, building id) — O02/O03 share one validated entrance.
DU_ORDERS = [
    ("O01", "kirori_mal", None),
    ("O02", "hansraj", "B-HANSRAJ"),
    ("O03", "hansraj", "B-HANSRAJ"),
    ("O04", "hindu_college", None),
    ("O05", "st_stephens", None),
    ("O06", "miranda_house", None),
    ("O07", "ramjas", None),
    ("O08", "srcc", None),
    ("O09", "daulat_ram", None),
    ("O10", "kamla_nagar", None),
    ("O11", "gtb_nagar", None),
    ("O12", "civil_lines", None),
]

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
    area: str = "bengaluru",
) -> DeliveryRound:
    """Three riders, two starts, three different endpoint types, 12 orders.

    Both areas use the same role ids (office, warehouse, home_r1, custom_r2) and
    order ids, so every check runs unchanged on either area.
    """
    orders_spec = DU_ORDERS if area == "du_north" else ORDERS
    locations = locations or load_locations(DU_LOCATIONS_FILE if area == "du_north" else LOCATIONS_FILE)
    riders = [
        Rider("R1", Vehicle.SCOOTER, 5, StartKind.OFFICE, Endpoint(EndpointKind.HOME, "home_r1", confirmed)),
        Rider("R2", Vehicle.BIKE, 5, StartKind.WAREHOUSE, Endpoint(EndpointKind.CUSTOM, "custom_r2", confirmed)),
        Rider("R3", Vehicle.SCOOTER, 4, StartKind.WAREHOUSE, Endpoint(EndpointKind.LAST_STOP, None, confirmed)),
    ]
    orders = [Order(oid, loc, bld) for oid, loc, bld in orders_spec]
    return DeliveryRound(
        id="phase0-demo",
        depots=Depots("office", "warehouse"),
        riders=riders,
        orders=orders,
        locations=locations,
        mode=mode,
    )
