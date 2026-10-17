"""Phase 2A: Office/Warehouse, rider profiles, per-round rider setup, rider-chosen destinations,
confirmation/version rules and planning readiness (no optimizer).

Locations are public OpenStreetMap places around DU North Campus from
tests/fixtures/public_locations_du_north.json. Their Office/Warehouse/Home/Custom roles are
SYNTHETIC labels, not real business locations or homes. Customers are synthetic."""

import json
import logging
import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from routewise_api.config import REPO_ROOT
from routewise_api.models import DeliveryRound, Order, Rider, User

from .conftest import Browser, make_user

DU = {p["id"]: p for p in json.loads((REPO_ROOT / "tests/fixtures/public_locations_du_north.json").read_text())["locations"]}
OFFICE, WAREHOUSE = DU["office"], DU["warehouse"]  # synthetic roles on public stations
HOME, CUSTOM = DU["home_r1"], DU["custom_r2"]  # synthetic roles on public stations
BENGALURU = {"lat": 12.9716, "lng": 77.5946}  # outside the service area
KINDS = ("office", "warehouse", "home", "last_stop", "custom")


def ll(p) -> dict:
    return {"lat": p["lat"], "lng": p["lng"]}


# ------------------------------------------------------------------ helpers


def set_depot(admin, kind, point, version=None, label=None):
    return admin.send("PUT", f"/api/admin/depots/{kind}",
                      json={"version": version, "label": label or f"{kind.title()} (synthetic)", **ll(point)})


def put_rider(admin, rid, rider_id, **body):
    return admin.send("PUT", f"/api/admin/rounds/{rid}/riders/{rider_id}", json=body)


def choose(rider, rid, kind, point=None):
    return rider.send("PUT", f"/api/rider/rounds/{rid}/destination", json={"kind": kind, **(ll(point) if point else {})})


def setup_of(rider, rid):
    return rider.get(f"/api/rider/rounds/{rid}")


def confirm(rider, rid, version=None):
    if version is None:
        version = setup_of(rider, rid).json()["config_version"]
    return rider.send("POST", f"/api/rider/rounds/{rid}/confirm", json={"config_version": version})


def readiness(admin, rid):
    return admin.get(f"/api/admin/rounds/{rid}/readiness").json()


def codes(r):
    return [b["code"] for b in r["configuration_blockers"]]


class World:
    pass


@pytest.fixture
def world(app, admin, db):
    """Admin, three riders (A scooter, B bike, C no default vehicle) and a round with two
    resolved synthetic orders at public DU points."""
    w = World()
    w.admin = admin
    ids = {}
    for name, display, vehicle in (("rider_a", "Rider A", "scooter"), ("rider_b", "Rider B", "bike"),
                                   ("rider_c", "Rider C", None)):
        u = make_user(app, name, "rider", rider_name=display, vehicle=vehicle)
        ids[name] = str(db.scalar(select(Rider.id).where(Rider.user_id == u.id)))
    w.a, w.b, w.c = ids["rider_a"], ids["rider_b"], ids["rider_c"]
    owner = db.scalar(select(User).where(User.username == "admin1"))
    rnd = DeliveryRound(name="Synthetic round", created_by=owner.id)
    db.add(rnd)
    db.flush()
    for i, place in enumerate(("kirori_mal", "hindu_college")):
        db.add(Order(order_code=f"RW-S{i}", round_id=rnd.id, source_row=i + 2, customer_name=f"Test Customer {i}",
                     product="Box", contact=f"0000000000{i}", location_link="geo:0,0", location_state="resolved",
                     lat=DU[place]["lat"], lng=DU[place]["lng"], location_source="geo_uri"))
    db.commit()
    w.rid = str(rnd.id)
    w.ra, w.rb, w.rc = Browser(app), Browser(app), Browser(app)
    for b, n in ((w.ra, "rider_a"), (w.rb, "rider_b"), (w.rc, "rider_c")):
        assert b.login(n).status_code == 200
    return w


@pytest.fixture
def ready_world(world):
    """Both depots set; Rider A (Office start) and Rider B (Warehouse start) set up and confirmed."""
    w = world
    assert set_depot(w.admin, "office", OFFICE).status_code == 200
    assert set_depot(w.admin, "warehouse", WAREHOUSE).status_code == 200
    assert put_rider(w.admin, w.rid, w.a, capacity=5, start="office").status_code == 200
    assert put_rider(w.admin, w.rid, w.b, capacity=4, start="warehouse").status_code == 200
    assert choose(w.ra, w.rid, "home", HOME).status_code == 200
    assert choose(w.rb, w.rid, "last_stop").status_code == 200
    assert confirm(w.ra, w.rid).status_code == 200 and confirm(w.rb, w.rid).status_code == 200
    assert readiness(w.admin, w.rid)["ready"] is True
    return w


def state(rider, rid):
    return setup_of(rider, rid).json()["confirmation"]["state"]


def input_version(admin, rid):
    return readiness(admin, rid)["input_version"]


# ------------------------------------------------------------------ Office and Warehouse


def test_depots_are_created_listed_and_edited_with_versions(world):
    w = world
    assert w.admin.get("/api/admin/depots").json() == {"office": None, "warehouse": None}
    r = set_depot(w.admin, "office", OFFICE)
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["in_service_area"] is True
    assert (r.json()["lat"], r.json()["lng"]) == (OFFICE["lat"], OFFICE["lng"])
    assert set_depot(w.admin, "office", OFFICE).status_code == 409  # create twice
    assert set_depot(w.admin, "warehouse", WAREHOUSE, version=1).status_code == 404  # edit before create
    assert set_depot(w.admin, "office", DU["gtb_nagar"], version=1).json()["version"] == 2
    assert set_depot(w.admin, "office", OFFICE, version=1).status_code == 409  # stale
    listed = w.admin.get("/api/admin/depots").json()
    assert listed["office"]["lat"] == DU["gtb_nagar"]["lat"] and listed["warehouse"] is None


@pytest.mark.parametrize("coords", [{"lat": 91, "lng": 77.2}, {"lat": 28.7, "lng": 181}, {"lat": 0, "lng": 0},
                                    BENGALURU, {"lat": "north", "lng": 77.2}, {"lat": None, "lng": 77.2}])
def test_invalid_or_out_of_area_depot_coordinates_are_rejected(world, coords):
    r = world.admin.send("PUT", "/api/admin/depots/office", json={"label": "Office (synthetic)", **coords})
    assert r.status_code == 422
    assert world.admin.get("/api/admin/depots").json()["office"] is None


def test_non_finite_depot_coordinates_are_rejected(world):
    body = '{"label": "Office (synthetic)", "lat": NaN, "lng": 77.2}'
    r = world.admin.send("PUT", "/api/admin/depots/office", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_depot_kind_and_label_are_validated(world):
    assert world.admin.send("PUT", "/api/admin/depots/home", json={"label": "x", **ll(OFFICE)}).status_code == 422
    assert world.admin.send("PUT", "/api/admin/depots/office", json={"label": "   ", **ll(OFFICE)}).status_code == 422
    assert world.admin.send("PUT", "/api/admin/depots/office", json={"label": "x" * 101, **ll(OFFICE)}).status_code == 422


# ------------------------------------------------------------------ rider profiles


def test_admin_lists_and_edits_rider_profiles(world):
    w = world
    riders = w.admin.get("/api/admin/riders").json()
    assert [r["display_name"] for r in riders] == ["Rider A", "Rider B", "Rider C"]
    assert set(riders[0]) == {"id", "username", "display_name", "default_vehicle", "account_active", "version"}
    r = w.admin.send("PATCH", f"/api/admin/riders/{w.c}", json={"version": 1, "display_name": " Rider C2 ",
                                                                  "default_vehicle": "bike"})
    assert r.status_code == 200 and (r.json()["display_name"], r.json()["default_vehicle"], r.json()["version"]) == \
        ("Rider C2", "bike", 2)
    assert w.admin.send("PATCH", f"/api/admin/riders/{w.c}", json={"version": 1, "display_name": "x"}).status_code == 409
    for bad in ({"version": 2, "default_vehicle": "bicycle"}, {"version": 2, "display_name": ""},
                {"version": 2, "display_name": "   "}):
        assert w.admin.send("PATCH", f"/api/admin/riders/{w.c}", json=bad).status_code == 422, bad
    assert w.admin.send("PATCH", f"/api/admin/riders/{uuid.uuid4()}", json={"version": 1}).status_code == 404


def test_profile_edit_does_not_invalidate_a_round_confirmation(ready_world):
    w = ready_world
    v = input_version(w.admin, w.rid)
    assert w.admin.send("PATCH", f"/api/admin/riders/{w.a}", json={"version": 1, "display_name": "Rider A1",
                                                                      "default_vehicle": "bike"}).status_code == 200
    assert state(w.ra, w.rid) == "confirmed" and readiness(w.admin, w.rid)["ready"] is True
    assert setup_of(w.ra, w.rid).json()["vehicle"] == "scooter"  # the round setup keeps its own vehicle
    assert input_version(w.admin, w.rid) == v


# ------------------------------------------------------------------ per-round rider setup


@pytest.mark.parametrize("start", ["office", "warehouse"])
def test_rider_is_added_with_vehicle_capacity_and_either_start(world, start):
    w = world
    r = put_rider(w.admin, w.rid, w.b, capacity=7, start=start)
    assert r.status_code == 200
    body = r.json()
    assert (body["vehicle"], body["capacity"], body["start"], body["participating"]) == ("bike", 7, start, True)
    assert body["config_version"] == 1 and body["confirmation"]["state"] == "not_confirmed"
    assert body["destination"] is None and "destination_missing" in [i["code"] for i in body["issues"]]
    assert [x["rider_id"] for x in w.admin.get(f"/api/admin/rounds/{w.rid}/riders").json()] == [w.b]


@pytest.mark.parametrize("capacity", [0, -1, 1001, 2.5, "3", True, None])
def test_invalid_capacities_are_rejected(world, capacity):
    r = put_rider(world.admin, world.rid, world.a, capacity=capacity, start="office")
    assert r.status_code == 422
    assert world.admin.get(f"/api/admin/rounds/{world.rid}/riders").json() == []


@pytest.mark.parametrize("field,value", [("vehicle", "bicycle"), ("vehicle", "car"), ("vehicle", ""),
                                         ("start", "home"), ("start", "last_stop"), ("start", None)])
def test_invalid_vehicles_and_starts_are_rejected(world, field, value):
    body = {"capacity": 3, "start": "office", "vehicle": "scooter", field: value}
    assert put_rider(world.admin, world.rid, world.a, **body).status_code == 422


def test_vehicle_defaults_from_profile_and_is_required_without_one(world):
    w = world
    assert put_rider(w.admin, w.rid, w.a, capacity=3, start="office").json()["vehicle"] == "scooter"
    r = put_rider(w.admin, w.rid, w.c, capacity=3, start="office")
    assert r.status_code == 422 and "vehicle" in r.json()["detail"]
    assert put_rider(w.admin, w.rid, w.c, capacity=3, start="office", vehicle="bike").status_code == 200


def test_round_rider_versions_unknown_ids_and_duplicates(world):
    w = world
    assert put_rider(w.admin, w.rid, w.a, capacity=3, start="office").status_code == 200
    assert put_rider(w.admin, w.rid, w.a, capacity=3, start="office").status_code == 409  # add twice
    assert put_rider(w.admin, w.rid, w.a, version=7, capacity=4).status_code == 409  # stale version
    assert put_rider(w.admin, w.rid, w.b, version=1, capacity=4).status_code == 404  # not in round yet
    assert put_rider(w.admin, w.rid, str(uuid.uuid4()), capacity=3, start="office").status_code == 404
    assert put_rider(w.admin, str(uuid.uuid4()), w.a, capacity=3, start="office").status_code == 404
    assert w.admin.get(f"/api/admin/rounds/{uuid.uuid4()}/riders").status_code == 404


def test_deactivated_accounts_cannot_be_added_or_re_added(world, db):
    w = world
    assert put_rider(w.admin, w.rid, w.b, capacity=3, start="office").status_code == 200
    assert put_rider(w.admin, w.rid, w.b, version=1, participating=False).status_code == 200
    db.execute(update(User).where(User.username.in_(["rider_a", "rider_b"])).values(active=False))
    db.commit()
    r = put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    assert r.status_code == 422 and "deactivated" in r.json()["detail"]
    assert put_rider(w.admin, w.rid, w.b, version=2, participating=True).status_code == 422
    assert put_rider(w.admin, w.rid, w.a, capacity=3, start="office", participating=False).status_code == 200


def test_database_constraints_back_the_api(world, db):
    w = world
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    choose(w.ra, w.rid, "last_stop")
    bad = [
        "UPDATE round_riders SET capacity = 0",
        "UPDATE round_riders SET capacity = 1001",
        "UPDATE round_riders SET vehicle = 'bicycle'",
        "UPDATE round_riders SET start_kind = 'home'",
        "UPDATE round_riders SET confirmed_version = config_version + 1, confirmed_at = now()",
        "UPDATE round_riders SET confirmed_version = config_version",  # without confirmed_at
        "UPDATE rider_endpoints SET kind = 'home'",  # Home without coordinates
        "UPDATE rider_endpoints SET lat = 28.7, lng = 77.2, location_source = 'manual_pin'",  # Last stop with them
        "UPDATE rider_endpoints SET kind = 'bus_stop'",
        "UPDATE delivery_rounds SET input_version = 0",
        f"INSERT INTO depots (kind, label, lat, lng, updated_by) SELECT 'home', 'x', 28.7, 77.2, id FROM users LIMIT 1",
        f"INSERT INTO depots (kind, label, lat, lng, updated_by) SELECT 'office', ' ', 28.7, 77.2, id FROM users LIMIT 1",
    ]
    for sql in bad:
        with pytest.raises(IntegrityError):
            db.execute(text(sql))
            db.commit()
        db.rollback()


# ------------------------------------------------------------------ rider destinations


@pytest.mark.parametrize("kind", KINDS)
def test_each_destination_kind_can_be_chosen_and_confirmed(world, kind):
    w = world
    set_depot(w.admin, "office", OFFICE)
    set_depot(w.admin, "warehouse", WAREHOUSE)
    put_rider(w.admin, w.rid, w.a, capacity=3, start="warehouse")
    point = {"home": HOME, "custom": CUSTOM}.get(kind)
    r = choose(w.ra, w.rid, kind, point)
    assert r.status_code == 200, r.text
    dest = r.json()["destination"]
    assert dest["kind"] == kind
    if kind in ("home", "custom"):
        assert (dest["lat"], dest["lng"]) == (point["lat"], point["lng"])  # the rider sees their own location
    elif kind == "last_stop":
        assert dest == {"kind": "last_stop", "open_route": True}
    else:
        assert dest["set"] is True and dest["label"]
    assert r.json()["start"]["kind"] == "warehouse" and r.json()["start"]["label"] == "Warehouse (synthetic)"
    c = confirm(w.ra, w.rid, r.json()["config_version"])
    assert c.status_code == 200 and c.json()["confirmation"]["state"] == "confirmed"
    assert readiness(w.admin, w.rid)["ready"] is True


@pytest.mark.parametrize("body", [
    {"kind": "home"}, {"kind": "custom", "lat": 28.7}, {"kind": "home", **BENGALURU},
    {"kind": "custom", "lat": 95, "lng": 77.2}, {"kind": "home", "lat": 0, "lng": 0},
    {"kind": "office", **ll(OFFICE)}, {"kind": "last_stop", **ll(HOME)}, {"kind": "warehouse", "lat": 28.7},
    {"kind": "garage"}, {},
])
def test_invalid_destinations_are_rejected(world, body):
    w = world
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    r = w.ra.send("PUT", f"/api/rider/rounds/{w.rid}/destination", json=body)
    assert r.status_code == 422
    assert setup_of(w.ra, w.rid).json()["destination"] is None


def test_riders_only_reach_their_own_participating_rounds(world):
    w = world
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    choose(w.ra, w.rid, "home", HOME)
    # B is not in the round: the round is invisible, exactly like a missing one.
    for r in (setup_of(w.rb, w.rid), choose(w.rb, w.rid, "last_stop"), confirm(w.rb, w.rid, 1)):
        assert r.status_code == 404 and r.json()["detail"] == "Round not found"
        assert str(HOME["lat"]) not in r.text
    assert w.rb.get("/api/rider/rounds").json() == []
    assert [x["round_id"] for x in w.ra.get("/api/rider/rounds").json()] == [w.rid]
    missing = str(uuid.uuid4())
    assert setup_of(w.ra, missing).status_code == 404 and confirm(w.ra, missing, 1).status_code == 404
    # Removing A from the round hides it from A too.
    put_rider(w.admin, w.rid, w.a, version=2, participating=False)
    assert setup_of(w.ra, w.rid).status_code == 404 and w.ra.get("/api/rider/rounds").json() == []
    # ...and a removed rider can no longer change or confirm anything in it.
    assert choose(w.ra, w.rid, "last_stop").status_code == 404
    assert confirm(w.ra, w.rid, 3).status_code == 404


def test_a_rider_cannot_see_or_change_another_riders_destination(world):
    w = world
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    put_rider(w.admin, w.rid, w.b, capacity=3, start="office")
    choose(w.ra, w.rid, "home", HOME)
    r = choose(w.rb, w.rid, "custom", CUSTOM)
    assert r.json()["destination"]["kind"] == "custom"
    mine = setup_of(w.rb, w.rid).text
    assert str(HOME["lat"]) not in mine and str(HOME["lng"]) not in mine
    assert setup_of(w.ra, w.rid).json()["destination"]["kind"] == "home"  # B's write touched only B
    # The API has no rider id in rider paths; a forged rider id in the body is ignored.
    r = w.rb.send("PUT", f"/api/rider/rounds/{w.rid}/destination", json={"kind": "last_stop", "rider_id": w.a})
    assert r.status_code == 200 and setup_of(w.ra, w.rid).json()["destination"]["kind"] == "home"


# ------------------------------------------------------------------ confirmation and version rules


def test_stale_confirmation_is_a_clear_conflict(world):
    w = world
    set_depot(w.admin, "office", OFFICE)
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    shown = choose(w.ra, w.rid, "last_stop").json()["config_version"]
    put_rider(w.admin, w.rid, w.a, version=shown, capacity=4)
    r = confirm(w.ra, w.rid, shown)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "configuration_changed" and detail["current_version"] == shown + 1
    assert "confirm again" in detail["message"]
    assert state(w.ra, w.rid) == "not_confirmed"
    assert confirm(w.ra, w.rid, shown + 1).status_code == 200


def test_confirmation_needs_a_complete_setup(world):
    w = world
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    r = confirm(w.ra, w.rid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "configuration_incomplete"
    assert {i["code"] for i in r.json()["detail"]["issues"]} == {"start_depot_missing", "destination_missing"}
    choose(w.ra, w.rid, "warehouse")
    assert {i["code"] for i in confirm(w.ra, w.rid).json()["detail"]["issues"]} == \
        {"start_depot_missing", "destination_depot_missing"}
    set_depot(w.admin, "office", OFFICE)
    set_depot(w.admin, "warehouse", WAREHOUSE)
    assert confirm(w.ra, w.rid).status_code == 200


@pytest.mark.parametrize("change", [
    {"capacity": 9}, {"vehicle": "bike"}, {"start": "warehouse"},
])
def test_admin_changes_to_start_vehicle_or_capacity_invalidate_confirmation(ready_world, change):
    w = ready_world
    before = setup_of(w.ra, w.rid).json()["config_version"]
    v = input_version(w.admin, w.rid)
    r = put_rider(w.admin, w.rid, w.a, version=before, **change)
    assert r.status_code == 200 and r.json()["confirmation"]["state"] == "outdated"
    assert r.json()["config_version"] == before + 1 and input_version(w.admin, w.rid) == v + 1
    assert state(w.ra, w.rid) == "outdated" and state(w.rb, w.rid) == "confirmed"  # only that rider
    ready = readiness(w.admin, w.rid)
    assert ready["ready"] is False and codes(ready) == ["confirmation_outdated"]
    assert ready["configuration_blockers"][0]["rider"] == "Rider A"
    assert confirm(w.ra, w.rid).status_code == 200 and readiness(w.admin, w.rid)["ready"] is True


def test_no_op_admin_edit_keeps_confirmation(ready_world):
    w = ready_world
    version = setup_of(w.ra, w.rid).json()["config_version"]
    v = input_version(w.admin, w.rid)
    r = put_rider(w.admin, w.rid, w.a, version=version, capacity=5, start="office", vehicle="scooter",
                  participating=True)
    assert r.status_code == 200 and r.json()["config_version"] == version
    assert state(w.ra, w.rid) == "confirmed" and input_version(w.admin, w.rid) == v


@pytest.mark.parametrize("kind,point", [("custom", CUSTOM), ("home", DU["gtb_nagar"]), ("office", None),
                                        ("last_stop", None)])
def test_destination_changes_invalidate_but_resaving_the_same_does_not(ready_world, kind, point):
    w = ready_world
    assert choose(w.ra, w.rid, "home", HOME).json()["confirmation"]["state"] == "confirmed"  # identical re-save
    r = choose(w.ra, w.rid, kind, point)
    assert r.json()["confirmation"]["state"] == "outdated"
    assert codes(readiness(w.admin, w.rid)) == ["confirmation_outdated"]


def test_removing_and_re_adding_a_rider_requires_a_new_confirmation(ready_world):
    w = ready_world
    version = setup_of(w.rb, w.rid).json()["config_version"]
    put_rider(w.admin, w.rid, w.b, version=version, participating=False)
    assert readiness(w.admin, w.rid)["ready"] is True  # a removed rider does not count
    assert readiness(w.admin, w.rid)["riders"] == {"participating": 1, "confirmed": 1}
    put_rider(w.admin, w.rid, w.b, version=version + 1, participating=True)
    assert state(w.rb, w.rid) == "outdated"
    assert codes(readiness(w.admin, w.rid)) == ["confirmation_outdated"]


def test_adding_a_participating_rider_blocks_until_they_confirm(ready_world):
    w = ready_world
    put_rider(w.admin, w.rid, w.c, capacity=2, start="office", vehicle="scooter")
    ready = readiness(w.admin, w.rid)
    assert ready["ready"] is False and codes(ready) == ["destination_missing", "not_confirmed"]
    assert all(b["rider"] == "Rider C" for b in ready["configuration_blockers"])
    choose(w.rc, w.rid, "last_stop")
    assert codes(readiness(w.admin, w.rid)) == ["not_confirmed"]
    confirm(w.rc, w.rid)
    assert readiness(w.admin, w.rid)["ready"] is True


def test_depot_coordinate_change_invalidates_only_riders_who_use_it(ready_world, app):
    w = ready_world
    make_user(app, "rider_d", "rider", rider_name="Rider D", vehicle="scooter")
    rd = Browser(app)
    rd.login("rider_d")
    d_id = [r for r in w.admin.get("/api/admin/riders").json() if r["username"] == "rider_d"][0]["id"]
    put_rider(w.admin, w.rid, d_id, capacity=2, start="warehouse")  # D: Warehouse start, Office destination
    choose(rd, w.rid, "office")
    confirm(rd, w.rid)
    # A starts at the Office; B starts at the Warehouse and ends at Last stop; D ends at the Office.
    office = w.admin.get("/api/admin/depots").json()["office"]
    v = input_version(w.admin, w.rid)
    r = set_depot(w.admin, "office", office, version=office["version"], label="Office renamed (synthetic)")
    assert r.json()["confirmations_invalidated"] == 0  # label only
    assert [state(x, w.rid) for x in (w.ra, w.rb, rd)] == ["confirmed"] * 3 and input_version(w.admin, w.rid) == v
    r = set_depot(w.admin, "office", DU["gtb_nagar"], version=office["version"] + 1)
    assert r.status_code == 200 and r.json()["confirmations_invalidated"] == 2
    assert [state(x, w.rid) for x in (w.ra, w.rb, rd)] == ["outdated", "confirmed", "outdated"]
    assert input_version(w.admin, w.rid) == v + 1
    assert codes(readiness(w.admin, w.rid)) == ["confirmation_outdated", "confirmation_outdated"]
    assert setup_of(w.ra, w.rid).json()["start"]["lat"] == DU["gtb_nagar"]["lat"]  # the rider sees what changed


def test_confirming_twice_is_idempotent(ready_world):
    w = ready_world
    v = input_version(w.admin, w.rid)
    first = setup_of(w.ra, w.rid).json()["confirmation"]
    again = confirm(w.ra, w.rid)
    assert again.status_code == 200 and again.json()["confirmation"] == first
    assert input_version(w.admin, w.rid) == v


def test_customer_text_edits_keep_confirmations_and_planning_version(ready_world):
    w = ready_world
    order = w.admin.get(f"/api/admin/rounds/{w.rid}/orders").json()[0]
    v = input_version(w.admin, w.rid)
    r = w.admin.send("PATCH", f"/api/admin/orders/{order['id']}",
                     json={"version": order["version"], "customer_name": "Test Customer Renamed", "product": "Bag",
                           "contact": "000 111", "instructions": "Ring twice"})
    assert r.status_code == 200
    assert input_version(w.admin, w.rid) == v
    assert state(w.ra, w.rid) == "confirmed" and state(w.rb, w.rid) == "confirmed"
    assert readiness(w.admin, w.rid)["ready"] is True


def test_order_pins_and_statuses_advance_the_planning_version_without_touching_confirmations(ready_world):
    w = ready_world
    order = w.admin.get(f"/api/admin/rounds/{w.rid}/orders").json()[0]
    v = input_version(w.admin, w.rid)
    r = w.admin.send("POST", f"/api/admin/orders/{order['id']}/pin", json={"version": order["version"], **ll(DU["srcc"])})
    assert r.status_code == 200 and input_version(w.admin, w.rid) == v + 1
    same = w.admin.send("POST", f"/api/admin/orders/{order['id']}/pin", json={"version": r.json()["version"], **ll(DU["srcc"])})
    assert same.status_code == 200 and input_version(w.admin, w.rid) == v + 1  # same pin: nothing changed
    s = w.admin.send("PATCH", f"/api/admin/orders/{order['id']}", json={"version": same.json()["version"], "status": "Postponed"})
    assert s.status_code == 200 and input_version(w.admin, w.rid) == v + 2
    link = w.admin.send("POST", f"/api/admin/orders/{order['id']}/location-link",
                        json={"version": s.json()["version"], "link": "https://www.google.com/maps?q=28.6912,77.2091"})
    assert link.status_code == 200 and input_version(w.admin, w.rid) == v + 3
    assert state(w.ra, w.rid) == "confirmed" and state(w.rb, w.rid) == "confirmed"


def test_every_accepted_configuration_change_advances_the_planning_version(world):
    w = world
    seen = [input_version(w.admin, w.rid)]

    def step(response):
        assert response.status_code == 200, response.text
        seen.append(input_version(w.admin, w.rid))

    step(set_depot(w.admin, "office", OFFICE))  # no rider uses it yet: no round changes
    step(put_rider(w.admin, w.rid, w.a, capacity=3, start="office"))
    step(choose(w.ra, w.rid, "last_stop"))
    step(confirm(w.ra, w.rid))
    step(put_rider(w.admin, w.rid, w.a, version=2, capacity=4))
    step(set_depot(w.admin, "office", DU["gtb_nagar"], version=1))
    assert seen == [1, 1, 2, 3, 4, 5, 6]


# ------------------------------------------------------------------ admin cannot act for riders; privacy


def test_admin_cannot_choose_or_confirm_for_a_rider(world, app):
    w = world
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    assert w.admin.send("PUT", f"/api/rider/rounds/{w.rid}/destination", json={"kind": "last_stop"}).status_code == 403
    assert w.admin.send("POST", f"/api/rider/rounds/{w.rid}/confirm", json={"config_version": 1}).status_code == 403
    admin_writes = [(m, p) for m, p in _routes(app) if p.startswith("/api/admin") and m != "GET"]
    assert not any("confirm" in p or "destination" in p or "endpoint" in p for _, p in admin_writes)
    # Fields that look like a confirmation are ignored by the admin setup endpoint.
    r = w.admin.send("PUT", f"/api/admin/rounds/{w.rid}/riders/{w.a}",
                     json={"version": 1, "confirmed_version": 1, "kind": "home", **ll(HOME)})
    assert r.status_code == 200 and r.json()["confirmation"]["state"] == "not_confirmed"
    assert r.json()["destination"] is None


def _routes(app):
    return [(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops]


def test_admin_responses_never_contain_home_or_custom_coordinates(ready_world, app, caplog):
    caplog.set_level(logging.DEBUG)
    w = ready_world
    put_rider(w.admin, w.rid, w.c, capacity=2, start="office", vehicle="bike")
    choose(w.rc, w.rid, "custom", CUSTOM)
    secrets = [str(HOME["lat"]), str(HOME["lng"]), str(CUSTOM["lat"]), str(CUSTOM["lng"])]
    responses = [w.admin.get(p) for p in ("/api/admin/depots", "/api/admin/riders", f"/api/admin/rounds/{w.rid}/riders",
                                          f"/api/admin/rounds/{w.rid}/readiness", "/api/admin/rounds",
                                          f"/api/admin/rounds/{w.rid}/orders")]
    responses.append(put_rider(w.admin, w.rid, w.a, version=setup_of(w.ra, w.rid).json()["config_version"], capacity=6))
    responses.append(set_depot(w.admin, "office", DU["gtb_nagar"], version=1))
    for r in responses:
        assert r.status_code == 200 and not any(s in r.text for s in secrets), r.request.url
    listed = {x["display_name"]: x for x in w.admin.get(f"/api/admin/rounds/{w.rid}/riders").json()}
    assert listed["Rider A"]["destination"] == {"kind": "home"} and listed["Rider C"]["destination"] == {"kind": "custom"}
    assert not any(s in r.getMessage() for r in caplog.records for s in secrets)


# ------------------------------------------------------------------ readiness


def test_readiness_walks_through_every_gate(world, db):
    w = world
    r = readiness(w.admin, w.rid)
    assert r["orders_ready"] is True and r["ready"] is False and codes(r) == ["no_participating_riders"]
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office")
    assert codes(readiness(w.admin, w.rid)) == ["start_depot_missing", "destination_missing", "not_confirmed"]
    set_depot(w.admin, "office", OFFICE)
    choose(w.ra, w.rid, "warehouse")
    assert codes(readiness(w.admin, w.rid)) == ["destination_depot_missing", "not_confirmed"]
    set_depot(w.admin, "warehouse", WAREHOUSE)
    assert codes(readiness(w.admin, w.rid)) == ["not_confirmed"]
    confirm(w.ra, w.rid)
    r = readiness(w.admin, w.rid)
    assert r["ready"] is True and r["configuration_blockers"] == [] and r["riders"] == {"participating": 1, "confirmed": 1}
    # A deactivated account blocks planning even with a current confirmation.
    db.execute(update(User).where(User.username == "rider_a").values(active=False))
    db.commit()
    assert codes(readiness(w.admin, w.rid)) == ["account_inactive"]


def test_existing_order_location_checks_still_block_a_fully_confirmed_round(ready_world, db):
    w = ready_world
    order = w.admin.get(f"/api/admin/rounds/{w.rid}/orders").json()[1]
    w.admin.send("POST", f"/api/admin/orders/{order['id']}/pin", json={"version": order["version"], **BENGALURU})
    r = readiness(w.admin, w.rid)
    assert r["ready"] is False and r["orders_ready"] is False and r["configuration_blockers"] == []
    assert r["blockers"] == [{"order_code": "RW-S1", "reason": "pin is outside the DU North Campus service area"}]
    db.execute(update(Order).where(Order.order_code == "RW-S1")
               .values(location_state="needs_correction", lat=None, lng=None, location_source=None))
    db.commit()
    assert readiness(w.admin, w.rid)["blockers"] == [{"order_code": "RW-S1", "reason": "location needs correction"}]


def test_destinations_invalid_after_service_area_change_block_without_leaking(ready_world, app):
    from dataclasses import replace

    from routewise_api.config import ServiceArea

    w = ready_world
    s = app.state.settings
    app.state.settings = replace(s, service_area=ServiceArea(south=28.69, west=77.20, north=28.70, east=77.22))
    try:
        r = readiness(w.admin, w.rid)
    finally:
        app.state.settings = s
    assert set(codes(r)) == {"destination_invalid", "start_depot_outside_area"}
    assert str(HOME["lat"]) not in json.dumps(r)


def test_readiness_counts_only_participating_riders_and_preserves_round_404(world):
    w = world
    assert w.admin.get(f"/api/admin/rounds/{uuid.uuid4()}/readiness").status_code == 404
    put_rider(w.admin, w.rid, w.a, capacity=3, start="office", participating=False)
    r = readiness(w.admin, w.rid)
    assert codes(r) == ["no_participating_riders"] and r["riders"] == {"participating": 0, "confirmed": 0}
