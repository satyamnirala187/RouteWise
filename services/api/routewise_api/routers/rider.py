"""Rider endpoints: a rider sees only orders assigned to them. Ownership is checked in the
query itself, so another rider's order is indistinguishable from a missing one (404)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from ..deps import CurrentUser, get_db, require_rider
from ..models import Assignment, Order

router = APIRouter(prefix="/api/rider", tags=["rider"], dependencies=[Depends(require_rider)])


def _rider_view(o: Order) -> dict:
    # Minimal fields for delivery; no admin-only data (source rows, links, notes).
    return {
        "id": str(o.id),
        "order_code": o.order_code,
        "customer_name": o.customer_name,
        "product": o.product,
        "contact": o.contact,
        "instructions": o.instructions,
        "lat": o.lat,
        "lng": o.lng,
        "status": o.status,
    }


def _own_orders(current: CurrentUser):
    return select(Order).join(Assignment, Assignment.order_id == Order.id).where(Assignment.rider_id == current.rider.id)


@router.get("/orders")
def my_orders(current: CurrentUser = Depends(require_rider), db: DBSession = Depends(get_db, scope="function")) -> list[dict]:
    return [_rider_view(o) for o in db.scalars(_own_orders(current).order_by(Order.order_code)).all()]


@router.get("/orders/{order_id}")
def my_order(order_id: uuid.UUID, current: CurrentUser = Depends(require_rider), db: DBSession = Depends(get_db, scope="function")) -> dict:
    order = db.scalar(_own_orders(current).where(Order.id == order_id))
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return _rider_view(order)
