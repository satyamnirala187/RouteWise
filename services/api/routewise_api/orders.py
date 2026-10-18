"""Order helpers shared by import, admin editing and the optimization readiness gate."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from .config import ServiceArea
from .importer import FIELD_LIMITS
from .locations import LocationResult
from .models import ORDER_STATUSES, Order

_CONTACT_CHARS = re.compile(r"^[0-9+\-() .]+$")


def next_order_code(db: DBSession) -> str:
    n = db.execute(text("SELECT nextval('order_code_seq')")).scalar_one()
    return f"RW-{n:06d}"


def apply_location(order: Order, loc: LocationResult) -> None:
    order.location_state = loc.state
    order.lat, order.lng = (loc.lat, loc.lng) if loc.resolved else (None, None)
    order.location_source = loc.source if loc.resolved else None
    order.location_note = (loc.note or None) if not loc.resolved else None


def validate_text(field: str, value: str | None, *, required: bool) -> str | None:
    """Returns a cleaned value or raises ValueError with an admin-facing message."""
    if value is None or not value.strip():
        if required:
            raise ValueError(f"{field} is required")
        return None
    value = value.strip()
    if len(value) > FIELD_LIMITS[field]:
        raise ValueError(f"{field} is longer than {FIELD_LIMITS[field]} characters")
    if field == "contact":
        if not _CONTACT_CHARS.match(value):
            raise ValueError("contact may contain only digits, spaces, +, -, ( ) and dots")
    return value


def order_lock_options() -> dict:
    """Row lock for any order edit: FOR NO KEY UPDATE. It serialises order edits but never blocks
    the KEY SHARE locks that plan commits take through foreign keys while holding the round lock,
    so the two lock groups cannot form a wait cycle. Always re-reads the row."""
    return {"with_for_update": {"key_share": True}, "populate_existing": True}


def validate_status(value: str) -> str:
    if value not in ORDER_STATUSES:
        raise ValueError("status must be one of Pending, Postponed, Completed")
    return value


def order_view(o: Order, area: ServiceArea, assigned_rider_id=None) -> dict:
    return {
        "id": str(o.id),
        "order_code": o.order_code,
        "round_id": str(o.round_id),
        "source_row": o.source_row,
        "customer_name": o.customer_name,
        "product": o.product,
        "contact": o.contact,
        "instructions": o.instructions,
        "location_link": o.location_link,
        "location": {
            "state": o.location_state,
            "lat": o.lat,
            "lng": o.lng,
            "source": o.location_source,
            "note": o.location_note,
            "in_service_area": (area.contains(o.lat, o.lng) if o.lat is not None and o.lng is not None else None),
        },
        "status": o.status,
        "version": o.version,
        "planning": {
            "locked_rider_id": str(o.locked_rider_id) if o.locked_rider_id else None,
            "first_priority": o.first_priority,
            "assigned_rider_id": str(assigned_rider_id) if assigned_rider_id else None,
        },
    }


def readiness_blockers(orders: list[Order], area: ServiceArea) -> list[dict]:
    """Optimization validity gate: an order may reach the optimizer only with a resolved pin
    inside the routing graph's service area. Phase 2 must call this before planning."""
    blockers = []
    for o in orders:
        if o.location_state != "resolved" or o.lat is None or o.lng is None:
            blockers.append({"order_code": o.order_code, "reason": "location needs correction"})
        elif not area.contains(o.lat, o.lng):
            blockers.append({"order_code": o.order_code, "reason": "pin is outside the DU North Campus service area"})
    return blockers


class NotReadyForPlanning(Exception):
    def __init__(self, blockers: list[dict]):
        super().__init__(f"{len(blockers)} order(s) are not ready for planning")
        self.blockers = blockers


def planning_input(orders: list[Order], area: ServiceArea) -> list[dict]:
    """The only path from stored orders to the optimizer. Refuses invalid locations."""
    blockers = readiness_blockers(orders, area)
    if blockers:
        raise NotReadyForPlanning(blockers)
    return [{"order_id": str(o.id), "lat": o.lat, "lng": o.lng, "building_id": o.building_id} for o in orders]
