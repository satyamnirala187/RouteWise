"""Step 3A: the rider's read-only delivery view.

Orders are synthetic customers on public DU North Campus OSM points; road costs come from the
recorded real local-Valhalla matrices (planning_world.py)."""

import logging
import uuid

from sqlalchemy import select, update

from routewise_api.models import Assignment, DeliveryRound, Order, PlanOrder, User

from .conftest import Browser, make_user
from .planning_world import PUBLIC_DU, add_orders, plan_now, world  # noqa: F401  (fixture)
from .test_planning import PRIVATE, routes, set_status
from .test_round_setup import choose, confirm, put_rider

ITEM_FIELDS = {"id", "order_code", "customer_name", "product", "contact", "instructions", "status", "version",
               "location", "location_issue"}  # version since 3B: status updates send the version they were shown


def deliveries(b, rid):
    return b.get(f"/api/rider/rounds/{rid}/deliveries")


def seq_codes(view) -> list[str]:
    return [o["order_code"] for s in view["sequence"] for o in s["orders"]]


def all_items(view) -> list[dict]:
    return [o for s in view["sequence"] for o in s["orders"]] + view["unsequenced"] + view["postponed"] + view["completed"]


def test_each_rider_sees_their_current_plan_sequence_and_nothing_else(world):
    w = world
    plan = plan_now(w)
    everyone = {code for code in w.codes}
    for name, route in routes(plan).items():
        r = deliveries(w.browsers[name], w.rid)
        assert r.status_code == 200, r.text
        view = r.json()
        expected = [o["order_code"] for s in route["stops"] for o in s["orders"]]
        assert seq_codes(view) == expected  # the saved route order, unchanged
        assert [s["seq"] for s in view["sequence"]] == [s["seq"] for s in route["stops"]]
        assert view["unsequenced"] == view["postponed"] == view["completed"] == []
        mine = {o["order_code"] for o in all_items(view)}
        assert mine == set(expected) and not (mine & (everyone - set(expected)))
        for item in all_items(view):
            assert set(item) == ITEM_FIELDS  # no source rows, links, notes, locks or priority flags
            place = PUBLIC_DU[w.codes[item["order_code"]]]
            assert item["location"] == {"lat": place["lat"], "lng": place["lng"]} and item["location_issue"] is None
            assert item["status"] == "Pending" and item["customer_name"].startswith("Test Customer P")
        vehicle, capacity, start, kind, point = w.spec[name]
        assert view["participating"] is True
        assert view["setup"]["start"]["kind"] == start and view["setup"]["start"]["label"] == f"{start.title()} (synthetic)"
        assert view["setup"]["destination"]["kind"] == kind and view["setup"]["confirmation"] == "confirmed"
        p = view["plan"]
        assert (p["version"], p["is_current"], p["out_of_date"], p["superseded_versions"]) == (1, True, False, 0)
        assert p["real_road"] is True and p["recorded"] is True
        assert p["route"]["start"]["kind"] == start and p["route"]["destination"]["kind"] == kind
        assert p["route"]["open_route"] is (kind == "last_stop")
        assert (p["route"]["road_distance_m"], p["route"]["road_duration_s"]) == (route["road_distance_m"], route["road_duration_s"])
        # Home/Custom coordinates (own or another rider's) are not part of this view at all.
        for s in PRIVATE:
            assert s not in r.text


def test_instructions_contact_and_product_are_shown_as_stored(world, db):
    w = world
    db.execute(update(Order).where(Order.order_code == "RW-P001")
               .values(instructions="Ring twice; second floor (synthetic)", contact="+91 00000-00001", product="Box & pens"))
    db.commit()
    plan = plan_now(w)
    owner = next(n for n, r in routes(plan).items() if any(o["order_code"] == "RW-P001" for s in r["stops"] for o in s["orders"]))
    item = next(o for o in all_items(deliveries(w.browsers[owner], w.rid).json()) if o["order_code"] == "RW-P001")
    assert item["instructions"] == "Ring twice; second floor (synthetic)"
    assert item["contact"] == "+91 00000-00001"  # the stored string, not a normalized number
    assert item["product"] == "Box & pens"
    other = next(o for o in all_items(deliveries(w.browsers[owner], w.rid).json()) if o["order_code"] != "RW-P001")
    assert other["instructions"] is None


def test_postponed_and_completed_are_separate_and_mark_the_plan_out_of_date(world):
    w = world
    plan = plan_now(w)
    name, route = next((n, r) for n, r in routes(plan).items() if len(r["stops"]) >= 3)
    codes = [o["order_code"] for s in route["stops"] for o in s["orders"]]
    set_status(w, codes[0], "Postponed")
    set_status(w, codes[1], "Completed")
    view = deliveries(w.browsers[name], w.rid).json()
    assert [o["order_code"] for o in view["postponed"]] == [codes[0]]
    assert [o["order_code"] for o in view["completed"]] == [codes[1]]
    assert view["postponed"][0]["status"] == "Postponed" and view["completed"][0]["status"] == "Completed"
    assert seq_codes(view) == codes[2:]  # the remaining Pending orders keep their saved order
    assert [s["seq"] for s in view["sequence"]] == [s["seq"] for s in route["stops"]][2:]  # original stop numbers
    assert view["plan"]["out_of_date"] is True and view["plan"]["version"] == 1  # not presented as re-optimized


def test_only_the_current_plan_is_used_never_a_superseded_one(world):
    w = world
    first = plan_now(w)
    assert put_rider(w.admin, w.rid, w.ids["Rider C"], version=2, capacity=1).status_code == 200
    assert confirm(w.browsers["Rider C"], w.rid).status_code == 200
    second = plan_now(w)
    assert second["version"] == 2
    changed = False
    for name, route in routes(second).items():
        view = deliveries(w.browsers[name], w.rid).json()
        assert seq_codes(view) == [o["order_code"] for s in route["stops"] for o in s["orders"]]
        assert view["plan"]["version"] == 2 and view["plan"]["superseded_versions"] == 1 and not view["plan"]["out_of_date"]
        changed |= seq_codes(view) != [o["order_code"] for s in routes(first)[name]["stops"] for o in s["orders"]]
    assert changed  # the two versions really differ, so the test can tell them apart


def test_own_destination_change_after_planning_keeps_the_saved_order_awaiting_recalculation(world):
    """4B (R23): the rider's own change invalidates only their route (awaiting recalculation); the
    round plan is not out of date and the saved order is still shown, never as a new route."""
    w = world
    plan = plan_now(w)
    b = w.browsers["Rider A"]
    assert choose(b, w.rid, "warehouse").status_code == 200
    view = deliveries(b, w.rid).json()
    assert view["setup"]["destination"]["kind"] == "warehouse" and view["setup"]["confirmation"] == "outdated"
    assert view["plan"]["route"]["destination"]["kind"] == "home"  # what the saved route was planned to
    assert view["plan"]["out_of_date"] is False
    assert view["plan"]["rider_route"]["awaiting_recalculation"] == "destination_changed"
    assert view["plan"]["rider_route"]["revision"] is None
    assert view["reroute"]["blocked"]["code"] == "NOT_CONFIRMED"  # confirm first, then recalculate
    assert seq_codes(view) == [o["order_code"] for s in routes(plan)["Rider A"]["stops"] for o in s["orders"]]
    other = deliveries(w.browsers["Rider B"], w.rid).json()
    assert other["plan"]["rider_route"]["awaiting_recalculation"] is None and other["setup"]["confirmation"] == "confirmed"


def test_no_plan_yet_and_assigned_orders_without_a_plan(app, admin, db, world):
    w = world
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    assert view["plan"] is None and view["sequence"] == [] and all_items(view) == []
    # A round with orders assigned but no plan at all (as in Phase 1 data): listed, not sequenced.
    owner = db.scalar(select(User).where(User.username == "admin1"))
    rnd = DeliveryRound(name="Assigned without a plan", created_by=owner.id)
    db.add(rnd)
    db.flush()
    codes = add_orders(db, rnd.id, ["kirori_mal", "hansraj"], start=50)
    for o in db.scalars(select(Order).where(Order.order_code.in_(list(codes)))).all():
        db.add(Assignment(order_id=o.id, rider_id=uuid.UUID(w.ids["Rider A"])))
    db.commit()
    view = deliveries(w.browsers["Rider A"], str(rnd.id)).json()
    assert view["participating"] is False and view["setup"] is None and view["plan"] is None
    assert sorted(o["order_code"] for o in view["unsequenced"]) == sorted(codes)
    listed = {r["round_id"]: r for r in w.browsers["Rider A"].get("/api/rider/delivery-rounds").json()}
    assert listed[str(rnd.id)]["orders"] == {"pending": 2, "postponed": 0, "completed": 0}
    assert listed[str(rnd.id)]["participating"] is False and listed[str(rnd.id)]["has_plan"] is False
    assert str(rnd.id) not in deliveries_rounds_of(w.browsers["Rider B"])


def deliveries_rounds_of(b) -> set[str]:
    return {r["round_id"] for r in b.get("/api/rider/delivery-rounds").json()}


def test_unusable_locations_never_get_navigation_coordinates(world, db):
    w = world
    plan = plan_now(w)
    name, route = next((n, r) for n, r in routes(plan).items() if len(r["stops"]) >= 2)
    a, b = [s["orders"][0]["order_code"] for s in route["stops"][:2]]
    db.execute(update(Order).where(Order.order_code == a).values(location_state="needs_correction", lat=None, lng=None))
    db.execute(update(Order).where(Order.order_code == b).values(lat=12.97, lng=77.59))  # resolved, outside the area
    db.commit()
    items = {o["order_code"]: o for o in all_items(deliveries(w.browsers[name], w.rid).json())}
    assert items[a]["location"] is None and "needs correction" in items[a]["location_issue"]
    assert items[b]["location"] is None and "outside the DU North Campus service area" in items[b]["location_issue"]
    assert "12.97" not in str(items[b])


def test_rider_who_left_a_round_still_sees_their_held_orders(world):
    w = world
    plan = plan_now(w)
    route = routes(plan)["Rider C"]
    codes = [o["order_code"] for s in route["stops"] for o in s["orders"]]
    for c in codes:
        set_status(w, c, "Completed")
    version = next(r["config_version"] for r in w.admin.get(f"/api/admin/rounds/{w.rid}/riders").json()
                   if r["rider_id"] == w.ids["Rider C"])
    assert put_rider(w.admin, w.rid, w.ids["Rider C"], version=version, participating=False).status_code == 200
    b = w.browsers["Rider C"]
    assert b.get(f"/api/rider/rounds/{w.rid}").status_code == 404  # no setup any more
    view = deliveries(b, w.rid).json()
    assert view["participating"] is False and view["setup"] is None
    assert sorted(o["order_code"] for o in view["completed"]) == sorted(codes) and view["sequence"] == []
    listed = {r["round_id"]: r for r in b.get("/api/rider/delivery-rounds").json()}
    assert listed[w.rid]["participating"] is False and listed[w.rid]["confirmation"] is None


def test_other_riders_rounds_and_ids_are_refused_like_missing_ones(app, world, browser):
    w = world
    plan_now(w)
    outsider = make_user(app, "rider_z", "rider", rider_name="Rider Z", vehicle="scooter")
    assert outsider is not None
    z = Browser(app)
    assert z.login("rider_z").status_code == 200
    missing = deliveries(z, uuid.uuid4())
    foreign = deliveries(z, w.rid)
    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json()  # indistinguishable from a round that does not exist
    assert "Test Customer" not in foreign.text
    assert z.get("/api/rider/delivery-rounds").json() == []
    assert deliveries(z, "not-a-uuid").status_code == 422
    # Admins are not riders; signed-out requests are refused before any lookup.
    assert w.admin.get(f"/api/rider/rounds/{w.rid}/deliveries").status_code == 403
    assert w.admin.get("/api/rider/delivery-rounds").status_code == 403
    anon = browser()
    assert anon.get(f"/api/rider/rounds/{w.rid}/deliveries").status_code == 401
    assert anon.get("/api/rider/delivery-rounds").status_code == 401


def test_a_rider_never_receives_another_riders_orders_even_if_the_plan_rows_disagree(world, db):
    """Defence in depth: the sequence is filtered by the assignment as well as the plan row."""
    w = world
    plan = plan_now(w)
    victim = routes(plan)["Rider B"]["stops"][0]["orders"][0]["order_code"]
    order_id = db.scalar(select(Order.id).where(Order.order_code == victim))
    # A plan row cannot point at two riders (one row per order per plan), so move the
    # ASSIGNMENT away from Rider B: B's plan row now disagrees with the owner.
    db.execute(update(Assignment).where(Assignment.order_id == order_id).values(rider_id=uuid.UUID(w.ids["Rider A"])))
    db.commit()
    assert db.scalar(select(PlanOrder.rider_id).where(PlanOrder.order_id == order_id)) == uuid.UUID(w.ids["Rider B"])
    b_view = deliveries(w.browsers["Rider B"], w.rid).json()
    assert victim not in {o["order_code"] for o in all_items(b_view)}
    a_view = deliveries(w.browsers["Rider A"], w.rid).json()
    assert victim in {o["order_code"] for o in a_view["unsequenced"]}  # owned, but not in A's saved route
    assert victim not in seq_codes(a_view)


def test_delivery_view_logs_no_customer_fields(world, caplog):
    caplog.set_level(logging.DEBUG)
    w = world
    plan_now(w)
    for b in w.browsers.values():
        assert b.get("/api/rider/delivery-rounds").status_code == 200
        assert deliveries(b, w.rid).status_code == 200
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Test Customer" not in text and "Synthetic parcel" not in text and "0000000" not in text
    for s in PRIVATE:
        assert s not in text
