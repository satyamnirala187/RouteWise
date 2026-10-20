"""Admin same-building stop groups (step 4C). Rules, locking and the chosen local default (identical
resolved pins, explicit admin confirmation, nothing automatic) are in routewise_api/stop_groups.py.

Responses carry order codes and versions only: no coordinates, no customer details beyond what the
admin order list already shows. Every mutation needs the admin session and the CSRF token."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .. import stop_groups
from ..config import Settings
from ..deps import get_db, get_now, get_settings, require_admin
from ..models import DeliveryRound, Order
from .admin import admin_order_view

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _refuse(exc: stop_groups.GroupRefused) -> HTTPException:
    return HTTPException(exc.status, exc.body())


class GroupOrder(BaseModel):
    id: uuid.UUID
    version: StrictInt


class GroupIn(BaseModel):
    orders: Annotated[list[GroupOrder], Field(min_length=1, max_length=1000)]


class UngroupIn(BaseModel):
    version: StrictInt


@router.get("/rounds/{round_id}/stop-groups")
def stop_group_overview(round_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"),
                        settings: Settings = Depends(get_settings)) -> dict:
    """Existing groups, and same-pin suggestions (orders of this round with exactly equal valid pins that
    are not yet one complete group). A suggestion is never applied by itself."""
    if db.get(DeliveryRound, round_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    orders = db.scalars(select(Order).where(Order.round_id == round_id)).all()
    return stop_groups.overview(list(orders), settings.service_area)


@router.post("/rounds/{round_id}/stop-groups")
def group_as_one_stop(round_id: uuid.UUID, body: GroupIn, db: DBSession = Depends(get_db, scope="function"),
                      settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    """Confirm these orders as ONE stop (admin action). All succeed or none do."""
    if db.get(DeliveryRound, round_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    try:
        changed, orders = stop_groups.create_group(db, round_id, [(o.id, o.version) for o in body.orders],
                                                   settings.service_area, now)
    except stop_groups.GroupRefused as exc:
        raise _refuse(exc) from None
    fields = stop_groups.fields_for_round(db, round_id, settings.service_area)
    codes = sorted(o.order_code for o in orders)
    return {"changed": changed, "group": {"id": orders[0].building_id, "orders": codes},
            "orders": [admin_order_view(db, o, settings, fields) for o in sorted(orders, key=lambda o: o.order_code)]}


@router.delete("/orders/{order_id}/stop-group")
def ungroup(order_id: uuid.UUID, body: UngroupIn, db: DBSession = Depends(get_db, scope="function"),
            settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    """Take one order out of its stop group. A group left with one order dissolves."""
    try:
        order, freed, remaining = stop_groups.ungroup_order(db, order_id, body.version, now)
    except stop_groups.GroupRefused as exc:
        raise _refuse(exc) from None
    fields = stop_groups.fields_for_round(db, order.round_id, settings.service_area)
    notice = f"{order.order_code} was taken out of its stop group."
    if freed:
        notice += f" {freed[0].order_code} was the only order left, so the group was dissolved."
    return {"notice": notice, "freed": [o.order_code for o in freed],
            "remaining": sorted(o.order_code for o in remaining),
            "orders": [admin_order_view(db, o, settings, fields) for o in [order, *freed]]}
