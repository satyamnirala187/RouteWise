"""Editable orders, statuses, manual pins, link correction and the optimization validity gate."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from routewise_api.models import Order
from routewise_api.orders import NotReadyForPlanning, planning_input

from .conftest import HEADER, PIN, upload, xlsx


@pytest.fixture
def round_with_orders(admin):
    data = xlsx([HEADER,
                 ["Test Customer 21", "Box", "00000000021", PIN, "Gate 2"],
                 ["Test Customer 22", "Bag", "00000000022", "https://www.google.com/maps/@28.68,77.20,17z", None]])
    p = upload(admin, data).json()
    rid = admin.send("POST", f"/api/admin/imports/{p['id']}/commit").json()["round_id"]
    return rid


def orders(admin, rid):
    return admin.get(f"/api/admin/rounds/{rid}/orders").json()


def test_rounds_and_orders_listing(admin, round_with_orders):
    rounds = admin.get("/api/admin/rounds").json()
    assert rounds[0]["orders"] == 2 and rounds[0]["needs_pin"] == 1
    assert rounds[0]["name"].startswith("Import 13 Oct 2026 14:30 IST")  # test clock 09:00 UTC = 14:30 IST
    o = orders(admin, round_with_orders)
    assert [x["order_code"] for x in o] == ["RW-001001", "RW-001002"]
    assert o[1]["location"]["state"] == "needs_correction" and "map view centre" in o[1]["location"]["note"]


def test_edit_fields_with_version_check(admin, round_with_orders):
    o = orders(admin, round_with_orders)[0]
    r = admin.send("PATCH", f"/api/admin/orders/{o['id']}",
                   json={"version": o["version"], "contact": " 011 0000 0021 ", "instructions": "Leave at desk"})
    assert r.status_code == 200
    body = r.json()
    assert body["contact"] == "011 0000 0021" and body["instructions"] == "Leave at desk" and body["version"] == 2
    stale = admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": 1, "product": "Changed"})
    assert stale.status_code == 409
    cleared = admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": 2, "clear_instructions": True})
    assert cleared.json()["instructions"] is None


def test_only_three_statuses_allowed_in_api_and_database(admin, round_with_orders, db):
    o = orders(admin, round_with_orders)[0]
    v = o["version"]
    for status in ("Postponed", "Completed", "Pending"):
        r = admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": v, "status": status})
        assert r.status_code == 200 and r.json()["status"] == status
        v += 1
    for bad in ("Shipped", "pending", "Cancelled", ""):
        assert admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": v, "status": bad}).status_code == 422
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE orders SET status = 'Delivered'"))
        db.commit()
    db.rollback()


def test_invalid_edits_rejected(admin, round_with_orders):
    o = orders(admin, round_with_orders)[0]
    for body in ({"customer_name": "   "}, {"contact": "call me"}, {"product": "x" * 501}):
        r = admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], **body})
        assert r.status_code == 422, body


def test_manual_pin_fallback_resolves_order(admin, round_with_orders, db):
    o = orders(admin, round_with_orders)[1]
    bad = admin.send("POST", f"/api/admin/orders/{o['id']}/pin", json={"version": o["version"], "lat": 0, "lng": 0})
    assert bad.status_code == 422
    assert admin.send("POST", f"/api/admin/orders/{o['id']}/pin",
                      json={"version": o["version"], "lat": 95, "lng": 0}).status_code == 422
    r = admin.send("POST", f"/api/admin/orders/{o['id']}/pin",
                   json={"version": o["version"], "lat": 28.6883, "lng": 77.2148})
    loc = r.json()["location"]
    assert r.status_code == 200 and loc["state"] == "resolved" and loc["source"] == "manual_pin"
    assert loc["in_service_area"] is True and "warning" not in r.json()


def test_pin_outside_service_area_warns_and_blocks_readiness(admin, round_with_orders):
    o = orders(admin, round_with_orders)[1]
    r = admin.send("POST", f"/api/admin/orders/{o['id']}/pin",
                   json={"version": o["version"], "lat": 12.9716, "lng": 77.5946})
    assert r.json()["location"]["in_service_area"] is False and "outside" in r.json()["warning"]
    ready = admin.get(f"/api/admin/rounds/{round_with_orders}/readiness").json()
    assert ready["ready"] is False and ready["blockers"][0]["reason"].startswith("pin is outside")


def test_location_link_correction(admin, round_with_orders):
    o = orders(admin, round_with_orders)[1]
    r = admin.send("POST", f"/api/admin/orders/{o['id']}/location-link",
                   json={"version": o["version"], "link": "https://www.google.com/maps?q=28.6912,77.2091"})
    assert r.json()["location"]["state"] == "resolved" and r.json()["location"]["source"] == "query"


def test_readiness_gate_blocks_until_every_pin_is_valid(admin, round_with_orders, db):
    r = admin.get(f"/api/admin/rounds/{round_with_orders}/readiness").json()
    assert r == {"ready": False, "orders": 2, "blockers": [{"order_code": "RW-001002", "reason": "location needs correction"}]}
    rows = db.scalars(select(Order).order_by(Order.source_row)).all()
    with pytest.raises(NotReadyForPlanning) as exc:
        planning_input(list(rows), admin.client.app.state.settings.service_area)
    assert exc.value.blockers[0]["order_code"] == "RW-001002"
    o = orders(admin, round_with_orders)[1]
    admin.send("POST", f"/api/admin/orders/{o['id']}/pin", json={"version": o["version"], "lat": 28.6883, "lng": 77.2148})
    assert admin.get(f"/api/admin/rounds/{round_with_orders}/readiness").json()["ready"] is True
    db.expire_all()
    inputs = planning_input(list(db.scalars(select(Order)).all()), admin.client.app.state.settings.service_area)
    assert len(inputs) == 2 and all(i["lat"] and i["lng"] for i in inputs)


def test_database_refuses_resolved_without_coordinates(db, round_with_orders):
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE orders SET location_state = 'resolved', lat = NULL, lng = NULL"))
        db.commit()
    db.rollback()
