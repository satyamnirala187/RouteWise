"""Admin planning endpoints (step 2B): distribution mode, owner locks, first-delivery priority,
optimization runs, and versioned plans. Locking and status rules are described in planning.py.

No response here carries Home/Custom destination coordinates; routes name the destination kind."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, StrictBool, StrictInt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from ..config import Settings
from ..deps import CurrentUser, get_db, get_now, get_settings, require_admin
from ..models import (
    ACTIVE_RUN_STATES,
    Assignment,
    DeliveryRound,
    Order,
    PlanningRun,
    PlanOrder,
    PlanRoute,
    Rider,
    RoundRider,
    RoutePlan,
)
from ..orders import readiness_blockers
from ..planning import PlanningRefused, PlanningService, capture, expire_overdue, fingerprint, plan_validity, prepare
from ..riders import bump_round_input, configuration_blockers, lock_depots_shared, lock_round
from ..routing.matrix.base import ProviderError
from .admin import admin_order_view

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

MAX_BULK = 1000  # the import limit


def planning_service(request: Request) -> PlanningService:
    return request.app.state.planning


def _refuse(exc: PlanningRefused):
    raise HTTPException(exc.status, exc.body())


def _err(code: int, key: str, message: str, details: list | None = None):
    raise HTTPException(code, {"code": key, "message": message, "details": details or []})


# ------------------------------------------------------------------ mode, locks, priority


class ModeIn(BaseModel):
    mode: Literal["equal", "smart", "manual"]


@router.put("/rounds/{round_id}/mode")
def set_mode(round_id: uuid.UUID, body: ModeIn, db: DBSession = Depends(get_db, scope="function")) -> dict:
    rnd = lock_round(db, round_id)
    if rnd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    if rnd.mode != body.mode:
        rnd.mode = body.mode
        db.flush()
        bump_round_input(db, round_id)
        db.refresh(rnd)
    return {"round_id": str(rnd.id), "mode": rnd.mode, "input_version": rnd.input_version}


def _participant(db: DBSession, round_id: uuid.UUID, rider_id: uuid.UUID) -> bool:
    rr = db.get(RoundRider, (round_id, rider_id))
    return rr is not None and rr.participating


def _check_lock(db: DBSession, order: Order, rider_id: uuid.UUID | None) -> str | None:
    """None if the lock is acceptable; otherwise the refusal code."""
    if rider_id is None:
        return None
    if not _participant(db, order.round_id, rider_id):
        return "INVALID_LOCK"
    if order.status != "Pending":
        owner = db.scalar(select(Assignment.rider_id).where(Assignment.order_id == order.id))
        if owner != rider_id:
            return "OWNERSHIP_CHANGE_UNSUPPORTED"
    return None


LOCK_MESSAGES = {
    "INVALID_LOCK": "Choose a rider who participates in this round.",
    "OWNERSHIP_CHANGE_UNSUPPORTED": "Postponed and Completed orders keep their current rider; handing an order over "
                                    "is not supported.",
}


class LockIn(BaseModel):
    version: StrictInt
    rider_id: uuid.UUID | None  # null clears the lock


@router.put("/orders/{order_id}/lock")
def set_lock(order_id: uuid.UUID, body: LockIn, db: DBSession = Depends(get_db, scope="function"),
             settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    order = db.get(Order, order_id, with_for_update={"key_share": True})
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.version != body.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "This order changed since you opened it; reload and try again")
    code = _check_lock(db, order, body.rider_id)
    if code:
        _err(422, code, LOCK_MESSAGES[code], [order.order_code])
    if order.locked_rider_id != body.rider_id:
        order.locked_rider_id = body.rider_id
        order.version += 1
        order.updated_at = now
        bump_round_input(db, order.round_id)
    return admin_order_view(db, order, settings)


class BulkOrder(BaseModel):
    id: uuid.UUID
    version: StrictInt


class BulkLockIn(BaseModel):
    rider_id: uuid.UUID | None
    orders: Annotated[list[BulkOrder], Field(min_length=1, max_length=MAX_BULK)]


@router.post("/rounds/{round_id}/locks")
def bulk_lock(round_id: uuid.UUID, body: BulkLockIn, db: DBSession = Depends(get_db, scope="function"),
              settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    """Manual assignment for many orders at once: all succeed or none do."""
    ids = sorted({o.id for o in body.orders})
    if len(ids) != len(body.orders):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Each order may appear only once")
    if db.get(DeliveryRound, round_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    # Same lock order as single order edits: order rows (sorted) first, then the round row.
    orders = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(ids)).order_by(Order.id)
                                          .with_for_update(key_share=True)).all()}
    if len(orders) != len(ids) or any(o.round_id != round_id for o in orders.values()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Some orders are not part of this round")
    stale = [orders[o.id].order_code for o in body.orders if orders[o.id].version != o.version]
    if stale:
        _err(409, "STALE_ORDERS", "These orders changed since you opened them; reload and try again.", stale)
    problems: dict[str, list[str]] = {}
    for o in orders.values():
        code = _check_lock(db, o, body.rider_id)
        if code:
            problems.setdefault(code, []).append(o.order_code)
    if problems:
        code, codes = next(iter(sorted(problems.items())))
        _err(422, code, LOCK_MESSAGES[code], codes)
    changed = 0
    for o in orders.values():
        if o.locked_rider_id != body.rider_id:
            o.locked_rider_id, o.version, o.updated_at = body.rider_id, o.version + 1, now
            changed += 1
    if changed:
        bump_round_input(db, round_id)
    db.flush()
    return {"changed": changed, "orders": [admin_order_view(db, orders[i], settings) for i in ids]}


class PriorityIn(BaseModel):
    version: StrictInt
    first_priority: StrictBool


@router.put("/orders/{order_id}/priority")
def set_priority(order_id: uuid.UUID, body: PriorityIn, db: DBSession = Depends(get_db, scope="function"),
                 settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    order = db.get(Order, order_id, with_for_update={"key_share": True})
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.version != body.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "This order changed since you opened it; reload and try again")
    if body.first_priority and order.status != "Pending":
        _err(422, "PRIORITY_NOT_PENDING", "Only a Pending order can be a rider's first delivery.", [order.order_code])
    if order.first_priority != body.first_priority:
        order.first_priority = body.first_priority
        order.version += 1
        order.updated_at = now
        bump_round_input(db, order.round_id)
    return admin_order_view(db, order, settings)


# ------------------------------------------------------------------ optimization runs


def run_view(run: PlanningRun, plan_version: int | None = None) -> dict:
    return {
        "id": str(run.id), "round_id": str(run.round_id), "state": run.state, "mode": run.mode,
        "input_version": run.input_version,
        "requested_at": run.requested_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": ({"code": run.error_code, "message": run.error_message, "details": run.error_details or []}
                  if run.error_code else None),
        "plan_version": plan_version,
        "timings": run.timings,
    }


@router.post("/rounds/{round_id}/optimize", status_code=status.HTTP_202_ACCEPTED)
def optimize(round_id: uuid.UUID, request: Request, current: CurrentUser = Depends(require_admin),
             db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings),
             now: datetime = Depends(get_now)) -> dict:
    """Validate everything, snapshot the input and queue a background run. Invalid input is
    refused here, before any work is scheduled."""
    service = planning_service(request)
    try:
        service.provider()
    except ProviderError:
        _err(503, "ROUTING_ENGINE_UNAVAILABLE",
             "The local road-routing data is not available on this server (build the Valhalla tiles). "
             "No plan can be made without real road distances.")
    lock_depots_shared(db)
    rnd = lock_round(db, round_id)
    if rnd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    active = db.scalar(select(PlanningRun).where(PlanningRun.round_id == round_id,
                                                 PlanningRun.state.in_(ACTIVE_RUN_STATES)))
    if active is not None:
        _err(409, "RUN_IN_PROGRESS", "A plan is already being computed for this round.", [str(active.id)])
    orders = db.scalars(select(Order).where(Order.round_id == round_id)).all()
    order_blockers = readiness_blockers(list(orders), settings.service_area)
    config_blockers, _ = configuration_blockers(db, round_id, settings.service_area)
    if order_blockers or config_blockers:
        _err(409, "NOT_READY", "Planning is blocked until every readiness item is resolved.",
             [f"{b['order_code']}: {b['reason']}" for b in order_blockers] + [b["reason"] for b in config_blockers])
    snap = capture(db, round_id)
    try:
        prepared = prepare(snap, settings)
    except PlanningRefused as exc:
        _refuse(exc)
    if not service.try_reserve():
        _err(503, "PLANNING_BUSY", "The planner is busy with other rounds; try again in a moment.")
    try:
        run = PlanningRun(round_id=round_id, state="queued", requested_by=current.user.id, requested_at=now,
                          input_version=snap.input_version, input_fingerprint=fingerprint(snap, settings.secret_key),
                          mode=snap.mode)
        db.add(run)
        db.commit()  # visible to the worker before it is queued; get_db's own commit is then a no-op
    except IntegrityError:
        db.rollback()
        service.release()
        _err(409, "RUN_IN_PROGRESS", "A plan is already being computed for this round.")
    except BaseException:
        service.release()
        raise
    service.submit(run.id, snap, prepared)
    return run_view(run)


def _plan_version_of(db: DBSession, run_id: uuid.UUID) -> int | None:
    return db.scalar(select(RoutePlan.version).where(RoutePlan.run_id == run_id))


@router.get("/planning-runs/{run_id}")
def get_run(run_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"),
            settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    run = db.get(PlanningRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Planning run not found")
    expire_overdue(db, run, now, settings.planning.stale_after_s)
    return run_view(run, _plan_version_of(db, run.id))


@router.get("/rounds/{round_id}/planning-runs")
def list_runs(round_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"),
              settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> list[dict]:
    if db.get(DeliveryRound, round_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    runs = db.scalars(select(PlanningRun).where(PlanningRun.round_id == round_id)
                      .order_by(PlanningRun.requested_at.desc(), PlanningRun.id).limit(50)).all()
    for run in runs:
        expire_overdue(db, run, now, settings.planning.stale_after_s)
    versions = dict(db.execute(select(RoutePlan.run_id, RoutePlan.version)
                               .where(RoutePlan.round_id == round_id)).all())
    return [run_view(r, versions.get(r.id)) for r in runs]


# ------------------------------------------------------------------ plans


def plan_view(db: DBSession, plan: RoutePlan, rnd: DeliveryRound) -> dict:
    names = dict(db.execute(select(Rider.id, Rider.display_name)).all())
    codes = dict(db.execute(select(Order.id, Order.order_code).where(Order.round_id == plan.round_id)).all())
    routes = db.scalars(select(PlanRoute).where(PlanRoute.plan_id == plan.id)).all()
    items = db.execute(select(PlanOrder).where(PlanOrder.plan_id == plan.id)
                       .order_by(PlanOrder.rider_id, PlanOrder.stop_seq, PlanOrder.order_id)).scalars().all()
    by_rider: dict = {}
    for it in items:
        by_rider.setdefault(it.rider_id, []).append(it)
    out_routes = []
    for r in sorted(routes, key=lambda r: (names.get(r.rider_id, ""), str(r.rider_id))):
        mine = by_rider.get(r.rider_id, [])
        stops: dict[int, list] = {}
        for it in mine:
            if it.role == "active":
                stops.setdefault(it.stop_seq, []).append({"id": str(it.order_id), "order_code": codes[it.order_id]})
        out_routes.append({
            "rider_id": str(r.rider_id), "rider": names.get(r.rider_id), "vehicle": r.vehicle, "profile": r.profile,
            "capacity": r.capacity, "start": r.start_kind, "destination": r.endpoint_kind, "open_route": r.open_route,
            "road_distance_m": r.road_distance_m, "road_duration_s": r.road_duration_s,
            "stops": [{"seq": seq, "orders": stops[seq]} for seq in sorted(stops)],
            "postponed": [{"id": str(i.order_id), "order_code": codes[i.order_id]} for i in mine if i.role == "postponed"],
            "completed": [{"id": str(i.order_id), "order_code": codes[i.order_id]} for i in mine if i.role == "completed"],
        })
    # Pending orders this plan does not route (e.g. returned from Postponed by a rider): they need
    # planning. Shown for the current plan only; history is reported as it was saved.
    unplanned: list[str] = []
    if plan.is_current:
        active = {it.order_id for it in items if it.role == "active"}
        unplanned = sorted(c for oid, c, st in db.execute(select(Order.id, Order.order_code, Order.status)
                                                         .where(Order.round_id == plan.round_id)).all()
                           if st == "Pending" and oid not in active)
    summary = dict(plan.summary)
    summary["ownership_changes"] = [
        {"order_code": c["order_code"], "from_rider": names.get(uuid.UUID(c["from_rider_id"])),
         "to_rider": names.get(uuid.UUID(c["to_rider_id"]))} for c in summary.get("ownership_changes", [])]
    return {
        "id": str(plan.id), "round_id": str(plan.round_id), "version": plan.version, "is_current": plan.is_current,
        **plan_validity(plan, rnd), "unplanned_pending": unplanned, "input_version": plan.input_version,
        "mode": plan.mode, "created_at": plan.created_at.isoformat(), "run_id": str(plan.run_id),
        "superseded_at": plan.superseded_at.isoformat() if plan.superseded_at else None,
        "distance_label": plan.distance_label, "provenance": plan.provenance, "warnings": plan.warnings,
        "summary": summary, "routes": out_routes,
        "attribution": "Road data © OpenStreetMap contributors (ODbL). Durations are traffic-free estimates.",
    }


def _round(db: DBSession, round_id: uuid.UUID) -> DeliveryRound:
    rnd = db.get(DeliveryRound, round_id)
    if rnd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    return rnd


@router.get("/rounds/{round_id}/plan")
def current_plan(round_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function")) -> dict:
    rnd = _round(db, round_id)
    plan = db.scalar(select(RoutePlan).where(RoutePlan.round_id == round_id, RoutePlan.is_current.is_(True)))
    if plan is None:
        _err(404, "NO_PLAN", "This round has no plan yet.")
    return plan_view(db, plan, rnd)


@router.get("/rounds/{round_id}/plans")
def list_plans(round_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function")) -> list[dict]:
    rnd = _round(db, round_id)
    plans = db.scalars(select(RoutePlan).where(RoutePlan.round_id == round_id).order_by(RoutePlan.version.desc())).all()
    return [{"version": p.version, "is_current": p.is_current, **plan_validity(p, rnd),
             "mode": p.mode, "created_at": p.created_at.isoformat(),
             "superseded_at": p.superseded_at.isoformat() if p.superseded_at else None,
             "total_road_distance_m": p.summary.get("total_road_distance_m"),
             "planned_orders": p.summary.get("planned_orders")} for p in plans]


@router.get("/rounds/{round_id}/plans/{version}")
def get_plan(round_id: uuid.UUID, version: int, db: DBSession = Depends(get_db, scope="function")) -> dict:
    rnd = _round(db, round_id)
    plan = db.scalar(select(RoutePlan).where(RoutePlan.round_id == round_id, RoutePlan.version == version))
    if plan is None:
        _err(404, "NO_PLAN", "No plan with this version.")
    return plan_view(db, plan, rnd)
