"""Admin-only endpoints: Excel import (preview → commit), rounds, order editing and pins."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from ..config import Settings
from ..deps import CurrentUser, get_db, get_now, get_settings, require_admin
from ..importer import MAX_FILE_BYTES, parse_workbook
from ..locations import LocationResult, manual_pin, resolve_link
from ..models import Assignment, DeliveryRound, ImportBatch, Order
from ..orders import (
    apply_location,
    next_order_code,
    order_view,
    readiness_blockers,
    validate_status,
    validate_text,
)
from ..riders import bump_round_input, configuration_blockers

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

PREVIEW_TTL = timedelta(hours=1)
DELIVERY_TZ = ZoneInfo("Asia/Kolkata")
MAX_SHORT_LINKS_PER_IMPORT = 100
_import_slots_lock = threading.Lock()


def _import_slots(request: Request) -> threading.BoundedSemaphore:
    with _import_slots_lock:
        slots = getattr(request.app.state, "import_slots", None)
        if slots is None:
            slots = request.app.state.import_slots = threading.BoundedSemaphore(
                request.app.state.settings.max_concurrent_imports)
        return slots


# ------------------------------------------------------------------ imports


def _preview_view(batch: ImportBatch) -> dict:
    return {"id": str(batch.id), "state": batch.state, "filename": batch.filename,
            "expires_at": batch.expires_at.isoformat(), "summary": batch.summary, "rows": batch.rows or []}


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def upload_import(  # sync on purpose: FastAPI runs it on a worker thread, never on the event loop
    request: Request,
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
) -> dict:
    filename = (file.filename or "upload.xlsx")[-255:]
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"file_errors": ["Upload an .xlsx workbook."]})
    slots = _import_slots(request)
    if not slots.acquire(blocking=False):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Another import is being checked; try again in a moment")
    try:
        data = file.file.read(MAX_FILE_BYTES + 1)  # bounded read (body also capped while streaming)
        return _build_preview(data, filename, current, db, settings, now)
    finally:
        slots.release()


def _build_preview(data: bytes, filename: str, current: CurrentUser, db: DBSession, settings: Settings,
                   now: datetime) -> dict:
    parsed = parse_workbook(data)
    rows_out = []
    short_links = 0
    deadline = time.monotonic() + settings.import_link_budget_s  # total for every link check in this import
    for row in parsed.rows:
        loc_out = None
        link = row.values.get("location")
        if link and not any(i["field"] == "location" and i["severity"] == "error" for i in row.issues):
            budget_left = time.monotonic() < deadline and short_links < MAX_SHORT_LINKS_PER_IMPORT
            allow = settings.resolve_short_links and budget_left
            reason = "link checks disabled" if not settings.resolve_short_links else "per-import link-check limit reached"
            loc = resolve_link(link, allow_network=allow, offline_reason=reason, deadline=deadline)
            if loc.note.startswith("short link") or loc.source == "short_link":
                short_links += 1
            loc_out = {"state": loc.state, "lat": loc.lat, "lng": loc.lng, "source": loc.source, "note": loc.note,
                       "in_service_area": settings.service_area.contains(loc.lat, loc.lng) if loc.resolved else None}
            if not loc.resolved:
                row.add("warning", "location", f"Location needs a pin: {loc.note}.")
            elif not loc_out["in_service_area"]:
                row.add("warning", "location", "Pin is outside the DU North Campus service area; check it.")
        rows_out.append({"row": row.row, "values": row.values, "issues": row.issues, "location": loc_out})
    errors = sum(1 for r in parsed.rows if r.has_error)
    summary = {
        "file_errors": parsed.file_errors,
        "file_warnings": parsed.file_warnings,
        "header_row": parsed.header_row,
        "mapping": parsed.mapping,
        "ignored_columns": parsed.ignored_columns,
        "total_rows": len(parsed.rows),
        "rows_with_errors": errors,
        "rows_with_warnings": sum(1 for r in parsed.rows if any(i["severity"] == "warning" for i in r.issues)),
        "needs_pin": sum(1 for r in rows_out if r["location"] and r["location"]["state"] != "resolved"),
        "can_commit": not parsed.file_errors and errors == 0 and len(parsed.rows) > 0,
    }
    batch = ImportBatch(created_by=current.user.id, expires_at=now + PREVIEW_TTL, state="preview",
                        filename=filename, summary=summary, rows=rows_out)
    db.add(batch)
    db.flush()
    return _preview_view(batch)


def _get_preview(db: DBSession, import_id: uuid.UUID, now: datetime) -> ImportBatch:
    """Row-locked read (SELECT ... FOR UPDATE). Every state transition (commit, discard,
    expiry) happens under this lock, so concurrent requests serialise on the batch row and
    the loser sees the winner's committed state. The lock is released when get_db commits,
    which happens before the response is sent."""
    batch = db.get(ImportBatch, import_id, with_for_update=True, populate_existing=True)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    if batch.state == "preview" and batch.expires_at < now:
        batch.state, batch.rows = "discarded", None
        db.commit()
        raise HTTPException(status.HTTP_410_GONE, "This preview expired; upload the file again")
    return batch


@router.get("/imports/{import_id}")
def get_import(import_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"), now: datetime = Depends(get_now)) -> dict:
    return _preview_view(_get_preview(db, import_id, now))


@router.post("/imports/{import_id}/commit")
def commit_import(
    import_id: uuid.UUID,
    current: CurrentUser = Depends(require_admin),
    db: DBSession = Depends(get_db, scope="function"),
    now: datetime = Depends(get_now),
) -> dict:
    batch = _get_preview(db, import_id, now)
    if batch.state != "preview":
        raise HTTPException(status.HTTP_409_CONFLICT, "This import was already saved or discarded")
    if not batch.summary.get("can_commit"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Fix the errors shown in the preview, then upload again")
    local = now.astimezone(DELIVERY_TZ)  # admins read times in Delhi, not UTC
    rnd = DeliveryRound(name=f"Import {local:%d %b %Y %H:%M} IST — {batch.filename}"[:120], created_by=current.user.id)
    db.add(rnd)
    db.flush()
    for r in batch.rows or []:
        v, loc = r["values"], r["location"] or {}
        order = Order(order_code=next_order_code(db), round_id=rnd.id, source_row=r["row"],
                      customer_name=v["name"], product=v["product"], contact=v["contact"],
                      instructions=v.get("instructions"), location_link=v["location"], status="Pending")
        apply_location(order, LocationResult(loc.get("state", "needs_correction"), loc.get("lat"), loc.get("lng"),
                                             loc.get("source"), loc.get("note") or "location not checked"))
        db.add(order)
    batch.state, batch.rows, batch.round_id = "committed", None, rnd.id  # drop the duplicate copy of customer data
    db.flush()
    count = db.scalar(select(func.count()).select_from(Order).where(Order.round_id == rnd.id))
    return {"round_id": str(rnd.id), "orders_created": count}


@router.delete("/imports/{import_id}")
def discard_import(import_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"), now: datetime = Depends(get_now)) -> dict:
    batch = _get_preview(db, import_id, now)
    if batch.state != "preview":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a preview can be discarded")
    batch.state, batch.rows = "discarded", None
    return {"ok": True}


# ------------------------------------------------------------------ rounds and orders


@router.get("/rounds")
def list_rounds(db: DBSession = Depends(get_db, scope="function")) -> list[dict]:
    rows = db.execute(
        select(DeliveryRound, func.count(Order.id),
               func.count(Order.id).filter(Order.location_state != "resolved"))
        .outerjoin(Order, Order.round_id == DeliveryRound.id)
        .group_by(DeliveryRound.id).order_by(DeliveryRound.created_at.desc())
    ).all()
    return [{"id": str(r.id), "name": r.name, "created_at": r.created_at.isoformat(), "orders": n,
             "needs_pin": pins} for r, n, pins in rows]


@router.get("/rounds/{round_id}/orders")
def list_orders(round_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings)) -> list[dict]:
    if db.get(DeliveryRound, round_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    rows = db.execute(select(Order, Assignment.rider_id).outerjoin(Assignment, Assignment.order_id == Order.id)
                      .where(Order.round_id == round_id).order_by(Order.source_row)).all()
    return [order_view(o, settings.service_area, owner) for o, owner in rows]


@router.get("/rounds/{round_id}/readiness")
def round_readiness(round_id: uuid.UUID, db: DBSession = Depends(get_db, scope="function"), settings: Settings = Depends(get_settings)) -> dict:
    """Planning gate (no optimizer yet). `blockers` keeps its Phase 1 meaning: order-location
    blockers. `configuration_blockers` adds the rider side: participating riders, depots,
    starts, destinations and current confirmations. No destination coordinates are returned."""
    rnd = db.get(DeliveryRound, round_id)
    if rnd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    orders = db.scalars(select(Order).where(Order.round_id == round_id)).all()
    blockers = readiness_blockers(list(orders), settings.service_area)
    orders_ready = not blockers and len(orders) > 0
    config_blockers, riders = configuration_blockers(db, round_id, settings.service_area)
    return {"ready": orders_ready and not config_blockers, "orders": len(orders), "orders_ready": orders_ready,
            "blockers": blockers, "configuration_blockers": config_blockers, "riders": riders,
            "input_version": rnd.input_version}


class OrderPatch(BaseModel):
    version: int
    customer_name: str | None = Field(default=None, max_length=1000)
    product: str | None = Field(default=None, max_length=2000)
    contact: str | None = Field(default=None, max_length=200)
    instructions: str | None = Field(default=None, max_length=4000)
    clear_instructions: bool = False
    status: str | None = None


class PinIn(BaseModel):
    version: int
    lat: float
    lng: float


class LinkIn(BaseModel):
    version: int
    link: str = Field(min_length=1, max_length=2048)


def admin_order_view(db: DBSession, order: Order, settings: Settings) -> dict:
    return order_view(order, settings.service_area, db.scalar(select(Assignment.rider_id)
                                                              .where(Assignment.order_id == order.id)))


def _locked_order(db: DBSession, order_id: uuid.UUID, version: int) -> Order:
    # FOR NO KEY UPDATE: serialises order edits but never blocks the KEY SHARE locks that plan
    # commits take through foreign keys while holding the round lock (no deadlock cycle).
    order = db.get(Order, order_id, with_for_update={"key_share": True})
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.version != version:
        raise HTTPException(status.HTTP_409_CONFLICT, "This order changed since you opened it; reload and try again")
    return order


def _bump(order: Order, now: datetime) -> None:
    order.version += 1
    order.updated_at = now


def _planning_fields(order: Order) -> tuple:
    return order.location_state, order.lat, order.lng, order.status


def _bump_if_planning_input_changed(db: DBSession, order: Order, before: tuple) -> None:
    """Pins and statuses are planning input; customer text is not, and never touches any
    rider's confirmation either."""
    if _planning_fields(order) != before:
        bump_round_input(db, order.round_id)


@router.patch("/orders/{order_id}")
def edit_order(order_id: uuid.UUID, body: OrderPatch, db: DBSession = Depends(get_db, scope="function"),
               settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    order = _locked_order(db, order_id, body.version)
    before = _planning_fields(order)
    try:
        if body.customer_name is not None:
            order.customer_name = validate_text("name", body.customer_name, required=True)
        if body.product is not None:
            order.product = validate_text("product", body.product, required=True)
        if body.contact is not None:
            order.contact = validate_text("contact", body.contact, required=True)
        if body.clear_instructions:
            order.instructions = None
        elif body.instructions is not None:
            order.instructions = validate_text("instructions", body.instructions, required=False)
        if body.status is not None:
            order.status = validate_status(body.status)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    _bump(order, now)
    _bump_if_planning_input_changed(db, order, before)
    return admin_order_view(db, order, settings)


@router.post("/orders/{order_id}/pin")
def set_manual_pin(order_id: uuid.UUID, body: PinIn, db: DBSession = Depends(get_db, scope="function"),
                   settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    order = _locked_order(db, order_id, body.version)
    loc = manual_pin(body.lat, body.lng)
    if not loc.resolved:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, loc.note)
    before = _planning_fields(order)
    apply_location(order, loc)
    _bump(order, now)
    _bump_if_planning_input_changed(db, order, before)
    view = admin_order_view(db, order, settings)
    if not view["location"]["in_service_area"]:
        view["warning"] = "This pin is outside the DU North Campus service area and will block planning."
    return view


@router.post("/orders/{order_id}/location-link")
def set_location_link(order_id: uuid.UUID, body: LinkIn, db: DBSession = Depends(get_db, scope="function"),
                      settings: Settings = Depends(get_settings), now: datetime = Depends(get_now)) -> dict:
    order = _locked_order(db, order_id, body.version)
    before = _planning_fields(order)
    order.location_link = body.link.strip()
    deadline = time.monotonic() + settings.link_budget_s
    apply_location(order, resolve_link(order.location_link, allow_network=settings.resolve_short_links,
                                       deadline=deadline))
    _bump(order, now)
    _bump_if_planning_input_changed(db, order, before)
    return admin_order_view(db, order, settings)
