"""Step 4C: same-building stop groups, against real PostgreSQL with the recorded real local-Valhalla
DU matrices.

Chosen local implementation default under test (not an independently approved permanent policy):
groups are suggested only for orders of one round with EXACTLY equal resolved, valid pins; an admin
must confirm before anything is grouped; nearby pins, names and address text never group anything;
identical pins may stay separate stops. Covers the admin rules and refusals, planning and a rider's
reroute (capacity, owner locks, priority, partial completion), the rider contract, immutable plan and
revision history, and races between group edits, pin edits, status updates, solves and plan commits.

Customers are synthetic; locations are public OSM points."""

import json
import logging
import threading
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy import update as sql_update
from sqlalchemy.exc import DataError, IntegrityError

from routewise_api import reroute as rr_mod
from routewise_api.models import DeliveryRound, Order, RevisionOrder, RoutePlan, RouteRevision
from routewise_api.routing import domain as dom
from routewise_api.routing import planner

from .conftest import Browser
from .planning_world import PUBLIC_DU, add_orders, make_world, optimize, orders_by_code, plan_now, wait_run
from .planning_world import world  # noqa: F401  (fixture)
from .test_planning import lock, priority, routes
from .test_planning_concurrency import Gate, Pause, _edit_committed_or_blocked
from .test_reroute import PauseRun, ask, frozen_rows, reroute_now, wait_reroute
from .test_rider_deliveries import all_items, deliveries, seq_codes
from .test_rider_status import _race, item, post_status, round_versions, update

# P001-P003 share one pin, P004-P005 share another, the rest are single.
GROUP_POINTS = ["hansraj", "hansraj", "hansraj", "kirori_mal", "kirori_mal", "hindu_college", "st_stephens",
                "miranda_house", "ramjas"]
G3 = ["RW-P001", "RW-P002", "RW-P003"]
G2 = ["RW-P004", "RW-P005"]
HANSRAJ = PUBLIC_DU["hansraj"]
KIRORI = PUBLIC_DU["kirori_mal"]


@pytest.fixture
def gw(app, admin, db):
    return make_world(app, admin, db, points=GROUP_POINTS)


def refs(w, codes):
    o = orders_by_code(w)
    return [{"id": o[c]["id"], "version": o[c]["version"]} for c in codes]


def group(w, codes=None, *, orders=None, rid=None):
    return w.admin.send("POST", f"/api/admin/rounds/{rid or w.rid}/stop-groups", json={"orders": orders or refs(w, codes)})


def ungroup(w, code, version=None):
    o = orders_by_code(w)[code]
    return w.admin.send("DELETE", f"/api/admin/orders/{o['id']}/stop-group",
                        json={"version": o["version"] if version is None else version})


def overview(w):
    r = w.admin.get(f"/api/admin/rounds/{w.rid}/stop-groups")
    assert r.status_code == 200, r.text
    return r.json()


def set_pin(w, code, lat, lng, *, version=None):
    o = orders_by_code(w)[code]
    return w.admin.send("POST", f"/api/admin/orders/{o['id']}/pin",
                        json={"version": o["version"] if version is None else version, "lat": lat, "lng": lng})


def set_link(w, code, link):
    o = orders_by_code(w)[code]
    return w.admin.send("POST", f"/api/admin/orders/{o['id']}/location-link", json={"version": o["version"], "link": link})


def err(r):
    return r.json()["detail"]


def db_orders(db, rid=None) -> dict:
    db.expire_all()
    q = select(Order) if rid is None else select(Order).where(Order.round_id == uuid.UUID(rid))
    return {o.order_code: o for o in db.scalars(q).all()}


def group_ids(db, codes) -> set:
    rows = db_orders(db)
    return {rows[c].building_id for c in codes}


def assert_groups_consistent(db, rid):
    """Every group has at least two members of this round with one identical resolved pin."""
    by_group: dict = {}
    for o in db_orders(db, rid).values():
        if o.building_id:
            by_group.setdefault(o.building_id, []).append(o)
    for members in by_group.values():
        assert len(members) >= 2, [m.order_code for m in members]
        assert len({(m.lat, m.lng) for m in members}) == 1 and all(m.location_state == "resolved" for m in members)


def stops_of(plan, name):
    return [[o["order_code"] for o in s["orders"]] for s in routes(plan)[name]["stops"]]


def lock_all(w, codes, rider):
    for c in codes:
        assert lock(w, c, rider).status_code == 200


def snapshot_columns(o: Order) -> dict:
    cols = {c.name: getattr(o, c.name) for c in Order.__table__.columns}
    for volatile in ("building_id", "version", "updated_at"):
        cols.pop(volatile)
    return cols


# ------------------------------------------------------------------ admin: suggestions and explicit grouping


def test_identical_pins_are_suggested_by_order_code_only_and_nothing_is_grouped_on_its_own(gw, db):
    w = gw
    o = orders_by_code(w)
    assert o["RW-P001"]["same_pin_as"] == ["RW-P002", "RW-P003"] and o["RW-P004"]["same_pin_as"] == ["RW-P005"]
    assert o["RW-P006"]["same_pin_as"] == [] and all(v["stop_group"] is None for v in o.values())
    ov = overview(w)
    assert ov["groups"] == []
    assert [[x["order_code"] for x in s["orders"]] for s in ov["suggestions"]] == [G3, G2]
    text_ = json.dumps(ov)
    assert str(HANSRAJ["lat"]) not in text_ and str(HANSRAJ["lng"]) not in text_ and '"lat"' not in text_  # codes only
    assert {r.building_id for r in db_orders(db).values()} == {None}


def test_untouched_identical_pins_stay_separate_stops_in_a_plan(gw):
    w = gw
    lock_all(w, G3, "Rider A")
    plan = plan_now(w)
    mine = [s for s in stops_of(plan, "Rider A") if set(s) & set(G3)]
    assert sorted(mine) == [[c] for c in G3]  # the same point, three navigation stops: the admin's choice is kept


def test_group_as_one_stop_is_explicit_server_generated_and_changes_only_the_group(gw, db):
    w = gw
    before = {c: snapshot_columns(o) for c, o in db_orders(db).items()}
    versions = round_versions(db, w.rid)
    r = group(w, G3)
    assert r.status_code == 200 and r.json()["changed"] is True, r.text
    body = r.json()
    gid = body["group"]["id"]
    assert body["group"]["orders"] == G3 and len(gid) == 32 and gid.strip("0123456789abcdef") == ""
    rows = db_orders(db)
    assert {rows[c].building_id for c in G3} == {gid} and all(rows[c].building_id is None for c in rows if c not in G3)
    assert all(rows[c].version == 2 for c in G3) and all(rows[c].version == 1 for c in rows if c not in G3)
    assert {c: snapshot_columns(o) for c, o in rows.items()} == before  # status, customer, pin, lock, priority, completion, owner
    assert round_versions(db, w.rid) == (versions[0] + 1, versions[1] + 1)  # planning input, once per request
    shown = orders_by_code(w)
    assert shown["RW-P002"]["stop_group"] == {"id": gid, "size": 3, "members": G3}
    assert [[x["order_code"] for x in s["orders"]] for s in overview(w)["suggestions"]] == [G2]  # a complete group is not suggested
    assert [g["id"] for g in overview(w)["groups"]] == [gid]


def test_a_client_cannot_choose_or_reuse_a_group_id(gw, db):
    w = gw
    body = {"orders": refs(w, G3), "building_id": "client-chosen-id", "id": "x"}
    r = w.admin.send("POST", f"/api/admin/rounds/{w.rid}/stop-groups", json=body)
    assert r.status_code == 200 and r.json()["group"]["id"] != "client-chosen-id"
    first = r.json()["group"]["id"]
    assert group(w, G2).json()["group"]["id"] != first  # every group gets its own fresh id


def test_nearby_pins_are_never_suggested_or_grouped(gw, db):
    w = gw
    assert set_pin(w, "RW-P006", HANSRAJ["lat"] + 0.000001, HANSRAJ["lng"]).status_code == 200  # about 10 cm away
    assert all("RW-P006" not in [x["order_code"] for x in s["orders"]] for s in overview(w)["suggestions"])
    assert "RW-P006" not in orders_by_code(w)["RW-P001"]["same_pin_as"]
    before = db_orders(db)
    versions = round_versions(db, w.rid)
    for codes in (["RW-P001", "RW-P006"], ["RW-P001", "RW-P002", "RW-P006"], ["RW-P001", "RW-P007"]):  # incl. campus neighbours
        r = group(w, codes)
        assert r.status_code == 422 and err(r)["code"] == "PINS_DIFFER", r.text
    after = db_orders(db)
    assert {c: o.version for c, o in after.items()} == {c: o.version for c, o in before.items()}
    assert {o.building_id for o in after.values()} == {None} and round_versions(db, w.rid) == versions


def test_orders_of_another_round_are_refused_and_never_suggested_together(gw, app, db):
    w = gw
    other = DeliveryRound(name="Second round", created_by=db.scalar(select(DeliveryRound.created_by)))
    db.add(other)
    db.flush()
    add_orders(db, other.id, ["hansraj", "hansraj"], start=51)  # the same pin, in another round
    codes_other = ["RW-P051", "RW-P052"]
    suggested = [x["order_code"] for s in overview(w)["suggestions"] for x in s["orders"]]
    assert not set(codes_other) & set(suggested)  # identical pins in different rounds are never suggested together
    other_orders = {o.order_code: o for o in db_orders(db, str(other.id)).values()}
    foreign = [{"id": str(other_orders[c].id), "version": other_orders[c].version} for c in codes_other]
    r = group(w, orders=refs(w, ["RW-P001"]) + foreign[:1])
    assert r.status_code == 404 and err(r)["code"] == "NOT_IN_ROUND"
    r = group(w, orders=foreign)  # the right orders, the wrong round
    assert r.status_code == 404
    assert group(w, rid=str(other.id), orders=foreign).status_code == 200  # in their own round they can be grouped
    assert group(w, rid=str(other.id), orders=refs(w, G3)).status_code == 404
    rows = db_orders(db)
    assert all(rows[c].building_id is None for c in G3) and rows["RW-P051"].building_id == rows["RW-P052"].building_id


def test_a_stale_version_refuses_the_whole_request(gw, db):
    w = gw
    o = orders_by_code(w)["RW-P002"]
    assert w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "product": "Changed"}).status_code == 200
    stale = refs(w, G3)
    stale[1]["version"] = o["version"]  # P002 as it was before that edit
    versions = round_versions(db, w.rid)
    r = group(w, orders=stale)
    assert r.status_code == 409 and err(r)["code"] == "STALE_ORDERS" and err(r)["details"] == ["RW-P002"]
    assert group_ids(db, G3) == {None} and round_versions(db, w.rid) == versions  # nothing partial
    assert group(w, G3).status_code == 200  # with fresh versions it works


def test_only_resolved_pins_inside_the_service_area_can_be_grouped(gw, db):
    w = gw
    far = (19.076, 72.8777)  # resolved, but outside the DU North Campus routing area
    assert set_pin(w, "RW-P007", *far).status_code == 200 and set_pin(w, "RW-P008", *far).status_code == 200
    r = group(w, ["RW-P007", "RW-P008"])
    assert r.status_code == 422 and err(r)["code"] == "LOCATION_NOT_VALID" and err(r)["details"] == ["RW-P007", "RW-P008"]
    assert [x["order_code"] for s in overview(w)["suggestions"] for x in s["orders"]].count("RW-P007") == 0
    assert set_link(w, "RW-P006", "not a map link").status_code == 200 and set_link(w, "RW-P009", "not a map link").status_code == 200
    r = group(w, ["RW-P006", "RW-P009"])
    assert r.status_code == 422 and err(r)["code"] == "LOCATION_NOT_VALID"
    assert {o.building_id for o in db_orders(db).values()} == {None}


def test_two_identical_out_of_area_pins_get_no_badge_and_no_suggestion(gw):
    w = gw
    far = (19.076, 72.8777)  # resolved, identical, but outside the DU North Campus routing area
    assert set_pin(w, "RW-P007", *far).status_code == 200 and set_pin(w, "RW-P008", *far).status_code == 200
    shown = orders_by_code(w)
    assert shown["RW-P007"]["same_pin_as"] == [] and shown["RW-P008"]["same_pin_as"] == []  # the badge follows the same rule
    assert shown["RW-P007"]["location"]["in_service_area"] is False  # the pin is stored and resolved: only the rule excludes it
    assert not {"RW-P007", "RW-P008"} & {x["order_code"] for s in overview(w)["suggestions"] for x in s["orders"]}
    assert group(w, ["RW-P007", "RW-P008"]).status_code == 422  # and the API refuses it as well
    assert shown["RW-P001"]["same_pin_as"] == ["RW-P002", "RW-P003"]  # valid identical pins are unaffected


def test_badges_and_suggestions_share_one_rule_and_group_membership_is_reported_on_its_own():
    from routewise_api.config import ServiceArea
    from routewise_api.stop_groups import overview, stop_group_fields

    area, rid = ServiceArea(), uuid.uuid4()

    def order(code, lat, lng, *, status="Pending", state="resolved", group=None):
        return Order(id=uuid.uuid4(), order_code=code, round_id=rid, status=status, location_state=state,
                     lat=lat if state == "resolved" else None, lng=lng if state == "resolved" else None, building_id=group)

    a = (HANSRAJ["lat"], HANSRAJ["lng"])
    far = (19.076, 72.8777)
    orders = [order("A1", *a), order("A2", *a), order("A3", *a, status="Completed"),         # valid pair + a completed one
              order("F1", *far), order("F2", *far),                                          # identical but outside the area
              order("N1", 0, 0, state="needs_correction"), order("N2", 0, 0, state="needs_correction"),
              order("G1", *far, group="abcdefgh12345678"), order("G2", *far, group="abcdefgh12345678")]  # grouped, pin not valid
    fields = stop_group_fields(orders, area)
    by = {o.order_code: fields[o.id] for o in orders}
    assert by["A1"]["same_pin_as"] == ["A2"] and by["A2"]["same_pin_as"] == ["A1"] and by["A3"]["same_pin_as"] == []
    assert all(by[c]["same_pin_as"] == [] for c in ("F1", "F2", "N1", "N2", "G1", "G2"))
    assert by["G1"]["stop_group"] == {"id": "abcdefgh12345678", "size": 2, "members": ["G1", "G2"]}  # membership stays visible
    assert by["F1"]["stop_group"] is None
    suggested = {x["order_code"] for s in overview(orders, area)["suggestions"] for x in s["orders"]}
    assert suggested == {"A1", "A2"}  # the panel suggests exactly the orders the badge names
    for o in orders:  # one rule: an ungrouped order has a badge if and only if it is in a suggestion
        if o.building_id is None:
            assert bool(by[o.order_code]["same_pin_as"]) == (o.order_code in suggested), o.order_code


def test_a_group_needs_at_least_two_different_orders(gw):
    w = gw
    r = group(w, ["RW-P001"])
    assert r.status_code == 422 and err(r)["code"] == "GROUP_TOO_SMALL"
    r = group(w, orders=refs(w, ["RW-P001", "RW-P001"]))
    assert r.status_code == 422 and err(r)["code"] == "DUPLICATE_ORDERS"
    assert w.admin.send("POST", f"/api/admin/rounds/{w.rid}/stop-groups", json={"orders": []}).status_code == 422
    r = group(w, orders=[{"id": str(uuid.uuid4()), "version": 1} for _ in range(101)])
    assert r.status_code == 422 and err(r)["code"] == "GROUP_TOO_LARGE"  # bounded request, refused before any lookup
    assert w.admin.send("POST", f"/api/admin/rounds/{uuid.uuid4()}/stop-groups", json={"orders": refs(w, G3)}).status_code == 404


def test_regrouping_is_idempotent_extends_by_replacing_and_never_splits_a_group_silently(gw, db):
    w = gw
    first = group(w, G3[:2]).json()["group"]["id"]
    versions = round_versions(db, w.rid)
    same = group(w, G3[:2])  # exactly the existing group
    assert same.status_code == 200 and same.json()["changed"] is False and same.json()["group"]["id"] == first
    assert round_versions(db, w.rid) == versions and db_orders(db)["RW-P001"].version == 2
    r = group(w, ["RW-P001", "RW-P003"])  # would take P001 out of its group of two and leave P002 behind
    assert r.status_code == 409 and err(r)["code"] == "GROUP_INCOMPLETE" and err(r)["details"] == ["RW-P002"]
    assert group_ids(db, G3[:2]) == {first}
    third = group(w, G3)  # whole group plus a new order: one group, one fresh id
    assert third.status_code == 200 and third.json()["changed"] is True
    gid = third.json()["group"]["id"]
    assert gid != first and group_ids(db, G3) == {gid}
    assert_groups_consistent(db, w.rid)


def test_ungroup_takes_one_order_out_and_a_group_of_one_dissolves(gw, db):
    w = gw
    gid = group(w, G3).json()["group"]["id"]
    versions = round_versions(db, w.rid)
    r = ungroup(w, "RW-P003")
    assert r.status_code == 200, r.text
    assert r.json()["freed"] == [] and r.json()["remaining"] == ["RW-P001", "RW-P002"] and "RW-P003" in r.json()["notice"]
    rows = db_orders(db)
    assert rows["RW-P003"].building_id is None and rows["RW-P001"].building_id == gid == rows["RW-P002"].building_id
    assert round_versions(db, w.rid) == (versions[0] + 1, versions[1] + 1)
    r = ungroup(w, "RW-P002")  # leaves P001 alone: the group dissolves
    assert r.json()["freed"] == ["RW-P001"] and r.json()["remaining"] == []
    assert group_ids(db, G3) == {None}
    assert db_orders(db)["RW-P001"].version == 3 and db_orders(db)["RW-P002"].version == 3  # grouped, then freed
    assert_groups_consistent(db, w.rid)
    r = ungroup(w, "RW-P001")
    assert r.status_code == 409 and err(r)["code"] == "NOT_GROUPED"
    group(w, G3)
    stale = ungroup(w, "RW-P001", version=1)
    assert stale.status_code == 409 and err(stale)["code"] == "STALE_ORDERS"
    assert w.admin.send("DELETE", f"/api/admin/orders/{uuid.uuid4()}/stop-group", json={"version": 1}).status_code == 404


def test_a_pin_edit_that_changes_the_pin_removes_the_order_from_its_group_with_a_notice(gw, db):
    w = gw
    gid = group(w, G3).json()["group"]["id"]
    same = set_pin(w, "RW-P002", HANSRAJ["lat"], HANSRAJ["lng"])  # the same pin again: nothing changed
    assert same.status_code == 200 and "stop_group_notice" not in same.json()
    assert db_orders(db)["RW-P002"].building_id == gid
    link_same = set_link(w, "RW-P002", f"geo:{HANSRAJ['lat']},{HANSRAJ['lng']}")  # a link that resolves to the same pin
    assert link_same.status_code == 200 and "stop_group_notice" not in link_same.json()
    assert db_orders(db)["RW-P002"].building_id == gid
    versions = round_versions(db, w.rid)
    r = set_pin(w, "RW-P003", KIRORI["lat"], KIRORI["lng"])
    assert r.status_code == 200
    assert "RW-P003 left its stop group because its pin changed" in r.json()["stop_group_notice"]
    assert r.json()["stop_group_freed"] == [] and r.json()["stop_group"] is None
    assert group_ids(db, G3[:2]) == {gid} and db_orders(db)["RW-P003"].building_id is None
    assert round_versions(db, w.rid) == (versions[0] + 1, versions[1] + 1)
    r = set_link(w, "RW-P002", f"geo:{KIRORI['lat']},{KIRORI['lng']}")  # leaves P001 alone: the group dissolves
    assert r.status_code == 200 and r.json()["stop_group_freed"] == ["RW-P001"]
    assert "only order left" in r.json()["stop_group_notice"]
    assert group_ids(db, G3) == {None} and db_orders(db)["RW-P001"].version == 3
    assert_groups_consistent(db, w.rid)


def test_a_link_that_no_longer_resolves_takes_the_order_out_of_its_group(gw, db):
    w = gw
    group(w, G3)
    r = set_link(w, "RW-P001", "not a map link")
    assert r.status_code == 200 and r.json()["location"]["state"] == "needs_correction"
    assert "left its stop group" in r.json()["stop_group_notice"] and r.json()["stop_group_freed"] == []
    assert db_orders(db)["RW-P001"].building_id is None and group_ids(db, G3[1:]) != {None}
    assert_groups_consistent(db, w.rid)


def test_grouping_an_order_of_any_status_never_changes_status_owner_lock_or_priority(gw, db):
    w = gw
    assert lock(w, "RW-P001", "Rider A").status_code == 200 and priority(w, "RW-P002").status_code == 200
    plan_now(w)  # ownership exists from here on
    o = orders_by_code(w)["RW-P003"]
    assert w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": "Postponed"}).status_code == 200
    owners = {c: v["planning"]["assigned_rider_id"] for c, v in orders_by_code(w).items()}
    flags = {c: (v["status"], v["planning"]["locked_rider_id"], v["planning"]["first_priority"]) for c, v in orders_by_code(w).items()}
    assert group(w, G3).status_code == 200 and ungroup(w, "RW-P002").status_code == 200
    now = orders_by_code(w)
    assert {c: v["planning"]["assigned_rider_id"] for c, v in now.items()} == owners
    assert {c: (v["status"], v["planning"]["locked_rider_id"], v["planning"]["first_priority"]) for c, v in now.items()} == flags


def test_group_endpoints_are_admin_only_and_need_the_csrf_token(gw, app, browser):
    w = gw
    url = f"/api/admin/rounds/{w.rid}/stop-groups"
    body = {"orders": refs(w, G3)}
    rider = w.browsers["Rider A"]
    o = orders_by_code(w)["RW-P001"]
    for method, path, kw in (("GET", url, {}), ("POST", url, {"json": body}),
                             ("DELETE", f"/api/admin/orders/{o['id']}/stop-group", {"json": {"version": 1}})):
        assert rider.send(method, path, **kw).status_code == 403
        assert browser().send(method, path, csrf=False, **kw).status_code == 401  # anonymous
    assert w.admin.send("POST", url, json=body, csrf=False).status_code == 403  # no CSRF token
    assert w.admin.send("POST", url, json=body, origin="https://evil.example").status_code == 403  # foreign origin
    assert w.admin.send("DELETE", f"/api/admin/orders/{o['id']}/stop-group", json={"version": 1}, csrf=False).status_code == 403
    assert group_ids(w.db, G3) == {None}


def test_group_actions_log_no_customer_fields(gw, caplog):
    w = gw
    caplog.set_level(logging.DEBUG)
    group(w, G3)
    set_pin(w, "RW-P003", KIRORI["lat"], KIRORI["lng"])
    ungroup(w, "RW-P002")
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("Test Customer P1", "0000000", str(HANSRAJ["lat"]), str(KIRORI["lat"])):
        assert secret not in log_text


# ------------------------------------------------------------------ planner rules (pure functions)


def _round(orders, riders=None):
    locs = {"L1": dom.Location("L1", "", 1.0, 1.0), "L2": dom.Location("L2", "", 2.0, 2.0)}
    riders = riders or [dom.Rider("A", dom.Vehicle.SCOOTER, 4, dom.StartKind.OFFICE, None),
                        dom.Rider("B", dom.Vehicle.SCOOTER, 3, dom.StartKind.OFFICE, None)]
    return dom.DeliveryRound(id="r", depots=dom.Depots("L1", "L2"), orders=orders, locations=locs, riders=riders)


def test_build_stops_groups_only_by_confirmed_building_and_keeps_priority_customers_first():
    orders = [dom.Order("o1", "L1", "b"), dom.Order("o2", "L1", "b", first_priority=True), dom.Order("o3", "L1"),
              dom.Order("o4", "L1"), dom.Order("o5", "L2", "b")]  # same point, no group / a group id at another point
    stops = planner.build_stops(_round(orders), [o.id for o in orders], 4)
    by_orders = {tuple(s.order_ids): s for s in stops}
    assert ("o2", "o1") in by_orders and by_orders[("o2", "o1")].priority and by_orders[("o2", "o1")].building_id == "b"
    assert ("o3",) in by_orders and ("o4",) in by_orders and ("o5",) in by_orders  # identical pin alone never groups


def test_build_stops_splits_for_capacity_and_owner_locks_without_dropping_orders():
    big = [dom.Order(f"g{i}", "L1", "b", first_priority=i in (4, 5)) for i in range(1, 7)]  # six orders, largest capacity 4
    stops = planner.build_stops(_round(big), [o.id for o in big], 4)
    assert [len(s.order_ids) for s in stops] == [4, 2] and sorted(sum((s.order_ids for s in stops), [])) == sorted(o.id for o in big)
    assert stops[0].order_ids[:2] == ["g4", "g5"] and stops[0].priority and not stops[1].priority  # priority fills the first chunk
    locked = [dom.Order("a1", "L1", "b", locked_rider_id="A"), dom.Order("b1", "L1", "b", locked_rider_id="B"),
              dom.Order("f1", "L1", "b")]
    stops = planner.build_stops(_round(locked), [o.id for o in locked], 4)
    assert sorted(tuple(s.order_ids) for s in stops) == [("a1",), ("b1",), ("f1",)]  # different locks: separate stops


def test_merge_gives_a_rider_one_stop_per_building_even_when_the_chunks_are_not_adjacent():
    a, b, c = (planner.StopSpec("L1", ["g1"], "b"), planner.StopSpec("L2", ["x"]), planner.StopSpec("L1", ["g2"], "b"))
    merged = planner.merge_building_stops([a, b, c])
    assert [(s.location_id, s.order_ids) for s in merged] == [("L1", ["g1", "g2"]), ("L2", ["x"])]
    other = planner.StopSpec("L1", ["z"], "other")  # a different building id at the same point stays its own stop
    assert len(planner.merge_building_stops([a, other, c])) == 2
    assert len(planner.merge_building_stops([planner.StopSpec("L1", ["x"]), planner.StopSpec("L1", ["y"])])) == 2


def test_stop_issues_flag_two_stops_at_a_group_and_a_misordered_priority_stop():
    orders = {"p": dom.Order("p", "L1", "b", first_priority=True), "q": dom.Order("q", "L1", "b"), "r": dom.Order("r", "L1", "b")}
    ok = [dom.Stop("L1", ["p", "q"], "b")]
    assert planner.stop_issues("A", ok, orders.__getitem__) == []
    assert planner.stop_issues("A", [dom.Stop("L1", ["q", "p"], "b")], orders.__getitem__)  # priority customer not first
    two = [dom.Stop("L1", ["p"], "b"), dom.Stop("L1", ["q"], "b")]
    assert any("two stops" in v for v in planner.stop_issues("A", two, orders.__getitem__))


# ------------------------------------------------------------------ planning: shared stops


def test_a_confirmed_group_is_one_stop_that_counts_every_order_for_capacity(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    assert group(w, G3).status_code == 200
    plan = plan_now(w)
    assert [sorted(s) for s in stops_of(plan, "Rider A") if set(s) & set(G3)] == [G3]
    total = sum(len(s) for s in stops_of(plan, "Rider A"))
    assert total <= 5  # capacity counts the three customers, not one stop
    assert routes(plan)["Rider A"]["capacity"] == 5
    owners = {c: v["planning"]["assigned_rider_id"] for c, v in orders_by_code(w).items()}
    assert {owners[c] for c in G3} == {w.ids["Rider A"]} and None not in owners.values()


def test_a_group_larger_than_every_rider_is_split_across_riders_with_one_stop_each(app, admin, db):
    w = make_world(app, admin, db, points=["hansraj", "hansraj", "hansraj", "kirori_mal", "hindu_college"], riders=[
        ("rider_a", "Rider A", "scooter", 2, "office", "home", "home_r1"),
        ("rider_b", "Rider B", "bike", 2, "warehouse", "custom", "custom_r2"),
        ("rider_c", "Rider C", "scooter", 2, "warehouse", "last_stop", None)])
    assert group(w, G3).status_code == 200
    plan = plan_now(w)
    owned = {c: v["planning"]["assigned_rider_id"] for c, v in orders_by_code(w).items()}
    assert None not in owned.values() and len(owned) == 5  # nothing dropped
    holders = {name: [s for s in stops_of(plan, name) if set(s) & set(G3)] for name in ("Rider A", "Rider B", "Rider C")}
    assert sorted(len(v) for v in holders.values()) == [0, 1, 1]  # one stop per applicable rider
    assert sorted(len(v[0]) for v in holders.values() if v) == [1, 2]  # capacity 2: chunks of two and one
    for name, route in routes(plan).items():
        assert sum(len(s["orders"]) for s in route["stops"]) <= 2
        assert {c for c in G3 if owned[c] == w.ids[name]} == {c for s in holders[name] for c in s}  # ownership = the plan's
    assert plan["summary"]["ownership_changes"] == []


def test_different_owner_locks_split_a_group_and_each_lock_is_respected(gw, db):
    w = gw
    assert lock(w, "RW-P001", "Rider A").status_code == 200 and lock(w, "RW-P002", "Rider B").status_code == 200
    assert lock(w, "RW-P003", "Rider A").status_code == 200
    assert group(w, G3).status_code == 200
    plan = plan_now(w)
    assert [sorted(s) for s in stops_of(plan, "Rider A") if set(s) & set(G3)] == [["RW-P001", "RW-P003"]]
    assert [s for s in stops_of(plan, "Rider B") if set(s) & set(G3)] == [["RW-P002"]]
    owners = {c: v["planning"]["assigned_rider_id"] for c, v in orders_by_code(w).items()}
    assert (owners["RW-P001"], owners["RW-P002"], owners["RW-P003"]) == (w.ids["Rider A"], w.ids["Rider B"], w.ids["Rider A"])


def test_an_unlocked_group_member_never_makes_a_rider_visit_the_building_twice(gw, db):
    w = gw
    assert lock(w, "RW-P001", "Rider A").status_code == 200  # the others are free
    assert group(w, G3).status_code == 200
    plan = plan_now(w)
    for name in ("Rider A", "Rider B", "Rider C"):
        assert len([s for s in stops_of(plan, name) if set(s) & set(G3)]) <= 1, name
    assert sorted(c for n in ("Rider A", "Rider B", "Rider C") for s in stops_of(plan, n) for c in s if c in G3) == G3


def test_several_priority_customers_in_one_group_make_one_priority_stop_listed_first(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    assert priority(w, "RW-P002").status_code == 200 and priority(w, "RW-P003").status_code == 200
    r = optimize(w)  # ungrouped: two first deliveries on one rider are a conflict
    assert r.status_code == 422 and err(r)["code"] == "PRIORITY_CONFLICT"
    assert group(w, G3).status_code == 200
    plan = plan_now(w)
    first = stops_of(plan, "Rider A")[0]
    assert first == ["RW-P002", "RW-P003", "RW-P001"]  # the stop is first; priority customers lead, then by code
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    assert [o["order_code"] for o in view["sequence"][0]["orders"]] == first and view["sequence"][0]["customers"] == 3
    assert not any("first_priority" in json.dumps(o) for o in all_items(view))  # the flag itself stays admin-only


def test_a_group_is_never_split_just_to_fit_capacity_and_the_failure_says_so(app, admin, db):
    w = make_world(app, admin, db, points=["hansraj"] * 4 + ["kirori_mal"] * 3 + ["hindu_college"] * 3, riders=[
        ("rider_a", "Rider A", "scooter", 5, "office", "home", "home_r1"),
        ("rider_b", "Rider B", "bike", 5, "warehouse", "custom", "custom_r2")])
    groups = (["RW-P001", "RW-P002", "RW-P003", "RW-P004"], ["RW-P005", "RW-P006", "RW-P007"], ["RW-P008", "RW-P009", "RW-P010"])
    for g in groups:
        assert group(w, g).status_code == 200
    svc = app.state.planning
    svc.limits = replace(svc.limits, solve_seconds=2)  # an infeasible search runs to its limit: keep the test short
    run = wait_run(w, optimize(w).json()["id"], timeout=60)  # 4 + 3 + 3 orders into capacities 5 and 5: no packing keeps all three groups whole
    assert run["state"] == "failed" and run["error"]["code"] == "NO_FEASIBLE_PLAN", run
    assert any("same-building stops" in d and "ungroup" in d for d in run["error"]["details"])  # the cause is named
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(RoutePlan)) == 0  # nothing saved, nothing silently split or dropped
    assert {o.building_id is not None for o in db_orders(db).values()} == {True}
    assert ungroup(w, "RW-P007").status_code == 200  # the admin's choice: let one order go separately
    plan = plan_now(w)
    owned = {c: v["planning"]["assigned_rider_id"] for c, v in orders_by_code(w).items()}
    assert len(owned) == 10 and None not in owned.values()  # every order has exactly one rider
    for name in ("Rider A", "Rider B"):
        assert sum(len(s) for s in stops_of(plan, name)) <= 5


def test_the_database_refuses_group_ids_that_break_the_rules(gw, db):
    broken = ("UPDATE orders SET building_id = 'abc' WHERE order_code = 'RW-P001'",                       # too short
              f"UPDATE orders SET building_id = '{'x' * 65}' WHERE order_code = 'RW-P001'",              # too long
              "UPDATE orders SET location_state = 'needs_correction', lat = NULL, lng = NULL, "
              "building_id = 'validgroupid0001' WHERE order_code = 'RW-P006'")                          # no resolved pin
    for statement in broken:
        with pytest.raises((IntegrityError, DataError)):  # the column is VARCHAR(64): too long is refused by the type itself
            db.execute(text(statement))
            db.commit()
        db.rollback()
    assert {o.building_id for o in db_orders(db).values()} == {None}


# ------------------------------------------------------------------ rider contract


def test_the_rider_sees_one_shared_stop_with_separate_customer_records(gw):
    w = gw
    lock_all(w, G3 + ["RW-P006"], "Rider A")
    group(w, G3)
    plan_now(w)
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    stop = next(s for s in view["sequence"] if {o["order_code"] for o in s["orders"]} == set(G3))
    assert stop["shared"] is True and stop["customers"] == 3
    assert stop["location"] == {"lat": HANSRAJ["lat"], "lng": HANSRAJ["lng"]} and stop["location_issue"] is None
    assert [o["order_code"] for o in stop["orders"]] == G3 and {o["status"] for o in stop["orders"]} == {"Pending"}
    assert all(o["location"] == stop["location"] for o in stop["orders"])  # one validated location, identical by construction
    single = next(s for s in view["sequence"] if s["orders"][0]["order_code"] not in G3)
    assert single["shared"] is False and single["customers"] == 1 and single["location"] == single["orders"][0]["location"]


def test_a_group_split_across_riders_shows_each_rider_only_their_own_customers(gw):
    w = gw
    assert lock(w, "RW-P001", "Rider A").status_code == 200
    lock_all(w, ["RW-P002", "RW-P003"], "Rider B")
    gid = group(w, G3).json()["group"]["id"]
    plan_now(w)
    a = deliveries(w.browsers["Rider A"], w.rid)
    b = deliveries(w.browsers["Rider B"], w.rid)
    assert [s["customers"] for s in a.json()["sequence"] if s["orders"][0]["order_code"] == "RW-P001"] == [1]
    stop_b = next(s for s in b.json()["sequence"] if s["orders"][0]["order_code"] in G3)
    assert [o["order_code"] for o in stop_b["orders"]] == ["RW-P002", "RW-P003"] and stop_b["shared"] and stop_b["customers"] == 2
    assert "RW-P002" not in a.text and "Test Customer P2" not in a.text and "RW-P001" not in b.text
    assert gid not in a.text and gid not in b.text  # the opaque group id is never sent to riders
    solo = deliveries(w.browsers["Rider A"], w.rid).json()["sequence"]
    assert next(s for s in solo if s["orders"][0]["order_code"] == "RW-P001")["shared"] is False  # a group of one for them


def test_partial_completion_and_postponement_leave_the_other_customers_together(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    group(w, G3)
    plan_now(w)
    versions = {c: o.version for c, o in db_orders(db).items()}
    update(w, "Rider A", "RW-P001", "Completed")
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    stop = next(s for s in view["sequence"] if s["orders"][0]["order_code"] in G3)
    assert [o["order_code"] for o in stop["orders"]] == ["RW-P002", "RW-P003"] and stop["customers"] == 2 and stop["shared"]
    assert {o["status"] for o in stop["orders"]} == {"Pending"}
    rows = db_orders(db)
    assert rows["RW-P002"].version == versions["RW-P002"] and rows["RW-P003"].version == versions["RW-P003"]  # untouched
    assert rows["RW-P001"].status == "Completed" and rows["RW-P002"].status == "Pending"
    update(w, "Rider A", "RW-P002", "Postponed")
    stop = next(s for s in deliveries(w.browsers["Rider A"], w.rid).json()["sequence"] if s["orders"][0]["order_code"] in G3)
    assert [o["order_code"] for o in stop["orders"]] == ["RW-P003"] and stop["customers"] == 1 and stop["shared"]  # still its group
    assert db_orders(db)["RW-P003"].version == versions["RW-P003"] and db_orders(db)["RW-P003"].status == "Pending"
    update(w, "Rider A", "RW-P003", "Completed")
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    assert not any(s["orders"][0]["order_code"] in G3 for s in view["sequence"])  # no Pending customer left: the stop is done
    assert [o["order_code"] for o in view["postponed"]] == ["RW-P002"]
    assert group_ids(db, G3) != {None}  # status changes never touch group membership


def test_a_returned_postponed_order_rejoins_its_group_at_the_next_reroute(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    group(w, G3)
    plan_now(w)
    update(w, "Rider A", "RW-P002", "Postponed")
    replanned = plan_now(w)  # the admin replans: the postponed order keeps its rider and is held off the sequence
    assert [sorted(s) for s in stops_of(replanned, "Rider A") if set(s) & set(G3)] == [["RW-P001", "RW-P003"]]
    update(w, "Rider A", "RW-P002", "Pending")  # returned, but outside the saved sequence
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    assert "RW-P002" in [o["order_code"] for o in view["unsequenced"]]  # nothing is reinserted automatically
    reroute_now(w, "Rider A", {"kind": "configured_start"})
    stops = deliveries(w.browsers["Rider A"], w.rid).json()["sequence"]
    stop = next(s for s in stops if s["orders"][0]["order_code"] in G3)
    assert [o["order_code"] for o in stop["orders"]] == G3 and stop["shared"] and stop["customers"] == 3  # back in its group


# ------------------------------------------------------------------ rider reroutes


def test_a_reroute_keeps_a_stop_group_together_and_leaves_plans_and_other_riders_alone(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    group(w, G3)
    plan_now(w)
    a_id = uuid.UUID(w.ids["Rider A"])
    before = frozen_rows(db, except_rider=a_id)
    reroute_now(w, "Rider A", {"kind": "configured_start"})
    assert frozen_rows(db, except_rider=a_id) == before  # the plan, assignments, orders and others' rows are byte-identical
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    assert view["plan"]["rider_route"]["revision"]["number"] == 1
    stops = [s for s in view["sequence"] if s["orders"][0]["order_code"] in G3]
    assert len(stops) == 1 and sorted(o["order_code"] for o in stops[0]["orders"]) == G3 and stops[0]["shared"]
    db.expire_all()
    rev = db.scalar(select(RouteRevision))
    seqs = set(db.scalars(select(RevisionOrder.stop_seq).join(Order, Order.id == RevisionOrder.order_id)
                          .where(RevisionOrder.revision_id == rev.id, Order.order_code.in_(G3))).all())
    assert len(seqs) == 1  # one stop in the stored revision


def test_a_reroute_groups_only_the_requesting_riders_own_pending_orders(gw, db):
    w = gw
    assert lock(w, "RW-P001", "Rider A").status_code == 200
    lock_all(w, ["RW-P002", "RW-P003"], "Rider B")
    group(w, G3)
    plan_now(w)
    a_id, b_id = uuid.UUID(w.ids["Rider A"]), uuid.UUID(w.ids["Rider B"])
    snap = rr_mod.capture_rider(db, uuid.UUID(w.rid), a_id, lock=False)
    assert "RW-P002" not in {o.order_code for o in snap.orders} and "RW-P001" in {o.order_code for o in snap.orders}
    before_a = frozen_rows(db, except_rider=b_id)
    reroute_now(w, "Rider B", {"kind": "configured_start"})
    assert frozen_rows(db, except_rider=b_id) == before_a
    b_view = deliveries(w.browsers["Rider B"], w.rid).json()
    stop = next(s for s in b_view["sequence"] if s["orders"][0]["order_code"] in G3)
    assert [o["order_code"] for o in stop["orders"]] == ["RW-P002", "RW-P003"] and stop["shared"] and stop["customers"] == 2
    a_after = deliveries(w.browsers["Rider A"], w.rid)
    assert "RW-P002" not in a_after.text and "RW-P003" not in a_after.text
    reroute_now(w, "Rider A", {"kind": "configured_start"})
    stop_a = next(s for s in deliveries(w.browsers["Rider A"], w.rid).json()["sequence"] if s["orders"][0]["order_code"] == "RW-P001")
    assert [o["order_code"] for o in stop_a["orders"]] == ["RW-P001"] and stop_a["customers"] == 1 and stop_a["shared"] is False


def test_a_reroute_keeps_several_priority_customers_of_a_group_as_one_first_stop(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    assert priority(w, "RW-P002").status_code == 200 and priority(w, "RW-P003").status_code == 200
    group(w, G3)
    plan_now(w)
    reroute_now(w, "Rider A", {"kind": "configured_start"})  # two first deliveries on one rider are fine inside one stop
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    first = view["sequence"][0]
    assert [o["order_code"] for o in first["orders"]] == ["RW-P002", "RW-P003", "RW-P001"] and first["customers"] == 3
    shown = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    rider_route = routes(shown)["Rider A"]["rider_route"]
    assert [o["order_code"] for o in rider_route["stops"][0]["orders"]] == ["RW-P002", "RW-P003", "RW-P001"]
    assert ungroup(w, "RW-P001").status_code == 200  # two ungrouped first deliveries are a conflict again
    r = ask(w, "Rider A", {"kind": "configured_start"})
    assert r.status_code == 409 and err(r)["code"] == "ROUND_OUT_OF_DATE"  # (the group change made the saved plan out of date first)


def test_a_group_change_during_a_reroute_solve_makes_it_stale(gw, db, app):
    w = gw
    lock_all(w, G3, "Rider A")
    group(w, G3)
    plan_now(w)
    pause = PauseRun(app.state.planning)
    r = ask(w, "Rider A", {"kind": "configured_start"})
    assert r.status_code == 202
    pause.wait()
    assert ungroup(w, "RW-P003").status_code == 200  # group input changed after the snapshot
    pause.go.set()
    run = wait_reroute(w, "Rider A", r.json()["id"])
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    db.expire_all()
    assert db.scalar(select(RouteRevision)) is None  # nothing saved


def _ungroup_behind_the_api(db, code="RW-P003"):
    """A membership change that bumps no version (as a future code path or a manual repair might),
    so only the fingerprint can notice it."""
    db.execute(sql_update(Order).where(Order.order_code == code).values(building_id=None))
    db.commit()


def test_the_rider_fingerprint_covers_group_membership_even_without_a_version_bump(gw, db, app):
    w = gw
    lock_all(w, G3, "Rider A")
    group(w, G3)
    plan_now(w)
    pause = PauseRun(app.state.planning)
    r = ask(w, "Rider A", {"kind": "configured_start"})
    assert r.status_code == 202
    pause.wait()
    _ungroup_behind_the_api(db)
    pause.go.set()
    run = wait_reroute(w, "Rider A", r.json()["id"])
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"


def test_the_plan_fingerprint_covers_group_membership_even_without_a_version_bump(gw, db, app):
    w = gw
    lock_all(w, G3, "Rider A")
    group(w, G3)
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    _ungroup_behind_the_api(db)
    pause.go.set()
    run = wait_run(w, run_id)
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(RoutePlan)) == 0


def test_a_reroute_refuses_after_a_group_change_until_the_admin_replans(gw):
    w = gw
    lock_all(w, G3, "Rider A")
    plan_now(w)
    assert group(w, G3).status_code == 200  # saved plan predates the group
    r = ask(w, "Rider A", {"kind": "configured_start"})
    assert r.status_code == 409 and err(r)["code"] == "ROUND_OUT_OF_DATE"


# ------------------------------------------------------------------ plans and history stay immutable


def _plan_rows(db) -> list:
    db.expire_all()
    out = []
    with db.bind.connect() as conn:
        for table in ("route_plans", "plan_routes", "plan_orders", "route_revisions", "revision_orders", "assignments"):
            out.append(sorted(r[0] for r in conn.execute(text(f"SELECT t::text FROM {table} t"))))
    return out


def test_group_changes_never_edit_saved_plans_or_revisions_and_mark_the_plan_out_of_date(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    plan_now(w)
    reroute_now(w, "Rider A", {"kind": "configured_start"})
    before = _plan_rows(db)
    versions = round_versions(db, w.rid)
    assert group(w, G3).status_code == 200
    assert _plan_rows(db) == before
    plan = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert plan["out_of_date"] is True and round_versions(db, w.rid) == (versions[0] + 1, versions[1] + 1)
    assert ungroup(w, "RW-P003").status_code == 200 and set_pin(w, "RW-P002", KIRORI["lat"], KIRORI["lng"]).status_code == 200
    assert _plan_rows(db) == before
    assert len([s for s in stops_of(plan, "Rider A") if set(s) & set(G3)]) == 3  # the saved stops are as they were planned


def test_a_new_plan_after_grouping_supersedes_the_old_one_and_keeps_its_history(gw, db):
    w = gw
    lock_all(w, G3, "Rider A")
    first = plan_now(w)
    assert len([s for s in stops_of(first, "Rider A") if set(s) & set(G3)]) == 3
    group(w, G3)
    second = plan_now(w)
    assert len([s for s in stops_of(second, "Rider A") if set(s) & set(G3)]) == 1
    old = w.admin.get(f"/api/admin/rounds/{w.rid}/plans/1").json()
    assert len([s for s in stops_of(old, "Rider A") if set(s) & set(G3)]) == 3  # version 1 is exactly as saved


# ------------------------------------------------------------------ in-flight solves and the commit


def test_a_group_change_during_an_admin_solve_makes_the_run_stale(gw, db, app):
    w = gw
    lock_all(w, G3, "Rider A")
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    assert group(w, G3).status_code == 200
    pause.go.set()
    run = wait_run(w, run_id)
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(RoutePlan)) == 0  # nothing was saved


def _group_edit(w):
    return group(w, G3)


def test_a_group_edit_racing_the_commit_after_its_final_check_has_a_serial_outcome(gw, db, db_url, app):
    w = gw
    lock_all(w, G3, "Rider A")
    gate = Gate(app.state.planning)
    run_id = optimize(w).json()["id"]
    assert gate.reached.wait(60)
    result = {}
    editor = threading.Thread(target=lambda: result.setdefault("response", _group_edit(w)))
    editor.start()
    engine = create_engine(db_url)
    try:
        edit_first = _edit_committed_or_blocked(engine, editor)
    finally:
        gate.go.set()
        engine.dispose()
    editor.join(30)
    assert not editor.is_alive() and result["response"].status_code == 200
    assert not edit_first  # the commit holds the round lock: the edit can only land after the plan
    run = wait_run(w, run_id)
    assert run["state"] == "succeeded"
    plan = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert plan["out_of_date"] is True  # the edit marks the plan that was just saved
    assert len([s for s in stops_of(plan, "Rider A") if set(s) & set(G3)]) == 3  # planned from the input before the group


# ------------------------------------------------------------------ concurrency among group edits


def test_two_overlapping_group_requests_have_exactly_one_winner(gw, db, db_url, app):
    w = gw
    big, small = refs(w, G3), refs(w, G3[1:])
    other = Browser(app)
    assert other.login("admin1").status_code == 200
    target = orders_by_code(w)["RW-P002"]["id"]  # a row both requests need
    results = _race(db_url, target, [lambda: group(w, orders=big),
                                     lambda: other.send("POST", f"/api/admin/rounds/{w.rid}/stop-groups", json={"orders": small})])
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    assert_groups_consistent(db, w.rid)
    rows = db_orders(db)
    members = [c for c in G3 if rows[c].building_id]
    assert members in (G3, G3[1:]) and len({rows[c].building_id for c in members}) == 1


def test_a_group_request_racing_a_pin_edit_of_a_member_has_a_serial_outcome(gw, db, db_url, app):
    w = gw
    grp = refs(w, ["RW-P001", "RW-P002"])
    o = orders_by_code(w)["RW-P002"]
    other = Browser(app)
    assert other.login("admin1").status_code == 200
    results = _race(db_url, o["id"], [
        lambda: group(w, orders=grp),
        lambda: other.send("POST", f"/api/admin/orders/{o['id']}/pin", json={"version": o["version"], "lat": KIRORI["lat"], "lng": KIRORI["lng"]})])
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    assert_groups_consistent(db, w.rid)
    rows = db_orders(db)
    if rows["RW-P001"].building_id:  # the group won: the late pin edit was refused as stale and changed nothing
        assert (rows["RW-P002"].lat, rows["RW-P002"].lng) == (HANSRAJ["lat"], HANSRAJ["lng"])
    else:  # the pin edit won: the group request was refused as stale and nothing was grouped
        assert (rows["RW-P002"].lat, rows["RW-P002"].lng) == (KIRORI["lat"], KIRORI["lng"])


def test_pin_edits_ungroup_and_bulk_locks_on_one_group_never_deadlock(gw, db, app):
    w = gw
    clients = [Browser(app) for _ in range(3)]
    assert all(c.login("admin1").status_code == 200 for c in clients)
    for _ in range(6):
        assert group(w, G3).status_code == 200
        o = orders_by_code(w)
        calls = (
            lambda: clients[0].send("POST", f"/api/admin/orders/{o['RW-P001']['id']}/pin", json={
                "version": o["RW-P001"]["version"], "lat": KIRORI["lat"], "lng": KIRORI["lng"]}),
            lambda: clients[1].send("DELETE", f"/api/admin/orders/{o['RW-P003']['id']}/stop-group",
                                    json={"version": o["RW-P003"]["version"]}),
            lambda: clients[2].send("POST", f"/api/admin/rounds/{w.rid}/locks", json={
                "rider_id": w.ids["Rider A"], "orders": [{"id": o[c]["id"], "version": o[c]["version"]} for c in G3]}))
        barrier = threading.Barrier(3)
        results = [None] * 3

        def go(i, fn):
            barrier.wait()
            results[i] = fn()

        threads = [threading.Thread(target=go, args=(i, fn)) for i, fn in enumerate(calls)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        assert not any(t.is_alive() for t in threads), "a request never finished (deadlock)"
        assert all(r.status_code in (200, 409) for r in results), [(r.status_code, r.text) for r in results]  # never a 500
        assert_groups_consistent(db, w.rid)
        db.execute(sql_update(Order).where(Order.order_code.in_(G3)).values(  # put the fixture back for the next round
            building_id=None, lat=HANSRAJ["lat"], lng=HANSRAJ["lng"], location_state="resolved", locked_rider_id=None))
        db.commit()


def test_a_status_update_racing_a_group_change_has_a_serial_outcome(gw, db, db_url):
    w = gw
    lock_all(w, G3, "Rider A")
    plan_now(w)
    b = w.browsers["Rider A"]
    o = item(deliveries(b, w.rid).json(), "RW-P001")
    grp = refs(w, G3)
    results = _race(db_url, o["id"], [lambda: post_status(b, o["id"], "Completed", o["version"]), lambda: group(w, orders=grp)])
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]  # exactly one winner
    assert_groups_consistent(db, w.rid)
    rows = db_orders(db)
    assert rows["RW-P002"].status == "Pending" and rows["RW-P003"].status == "Pending"
    if results[0].status_code == 200:  # the rider won: nothing was grouped, and only P001 changed
        assert rows["RW-P001"].status == "Completed" and group_ids(db, G3) == {None}
    else:  # the group won and bumped the version: the rider's late request was refused, not applied
        assert rows["RW-P001"].status == "Pending" and len(group_ids(db, G3)) == 1 and None not in group_ids(db, G3)
