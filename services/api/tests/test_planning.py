"""Phase 2B planning behaviour on recorded real local-Valhalla matrices (DU North Campus).

Customers are synthetic; locations are public OSM points (see planning_world.py)."""

import json
import logging
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from routewise_api.models import Assignment, Order, PlanningRun, RoutePlan

from .planning_world import (
    PUBLIC_DU,
    RECORDINGS,
    make_world,
    optimize,
    orders_by_code,
    plan_now,
    recorded_cost,
    route_points,
    wait_run,
    world,  # noqa: F401  (fixture)
)
from .recorded_matrix import RecordedDUProvider
from .test_round_setup import choose, confirm, put_rider, setup_of

PRIVATE = [str(PUBLIC_DU["home_r1"]["lat"]), str(PUBLIC_DU["home_r1"]["lng"]),
           str(PUBLIC_DU["custom_r2"]["lat"]), str(PUBLIC_DU["custom_r2"]["lng"])]


def all_codes(plan) -> list[str]:
    return [o["order_code"] for r in plan["routes"] for s in r["stops"] for o in s["orders"]]


def routes(plan) -> dict:
    return {r["rider"]: r for r in plan["routes"]}


def run_count(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(PlanningRun))


def set_mode(w, mode):
    assert w.admin.send("PUT", f"/api/admin/rounds/{w.rid}/mode", json={"mode": mode}).status_code == 200


def lock(w, code, rider):
    o = orders_by_code(w)[code]
    return w.admin.send("PUT", f"/api/admin/orders/{o['id']}/lock",
                        json={"version": o["version"], "rider_id": w.ids[rider] if rider else None})


def priority(w, code, flag=True):
    o = orders_by_code(w)[code]
    return w.admin.send("PUT", f"/api/admin/orders/{o['id']}/priority", json={"version": o["version"], "first_priority": flag})


def set_status(w, code, status):
    o = orders_by_code(w)[code]
    r = w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": status})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ smart plan: the full contract


def test_smart_plan_covers_every_order_once_with_real_directed_costs(world):
    w = world
    plan = plan_now(w)
    codes = all_codes(plan)
    assert sorted(codes) == sorted(w.codes) and len(codes) == len(set(codes))  # each Pending order exactly once
    assert plan["version"] == 1 and plan["is_current"] and not plan["out_of_date"]
    prov = plan["provenance"]
    assert prov["real_road"] is True and prov["recorded"] is True and prov["metric"] == "distance"
    assert "OpenStreetMap" in prov["notes"] and plan["distance_label"].startswith("Road distances: valhalla-local")
    rs = routes(plan)
    for name, (vehicle, capacity, start, kind, point) in w.spec.items():
        r = rs[name]
        assert (r["vehicle"], r["start"], r["destination"], r["capacity"]) == (vehicle, start, kind, capacity)
        assert r["profile"] == {"scooter": "motor_scooter", "bike": "motorcycle"}[vehicle]
        assert r["open_route"] is (kind == "last_stop")
        assert len(r["stops"]) <= capacity
        # Reported distance = the recorded directed matrix of that rider's own profile along the
        # route; an open route stops at the last delivery (no artificial final arc).
        assert (r["road_distance_m"], r["road_duration_s"]) == recorded_cost(r["profile"], route_points(w, r))
    assert plan["summary"]["total_road_distance_m"] == sum(r["road_distance_m"] for r in plan["routes"])
    # Directed: travelling the same stops backwards would cost a different amount on real roads.
    asym = [r for r in plan["routes"] if len(r["stops"]) > 1
            and recorded_cost(r["profile"], route_points(w, r)[::-1]) != recorded_cost(r["profile"], route_points(w, r))]
    assert asym


def test_assignments_follow_the_plan_and_riders_see_only_their_own(world, db):
    w = world
    plan = plan_now(w)
    owners = {o["order_code"]: o["planning"]["assigned_rider_id"] for o in orders_by_code(w).values()}
    for r in plan["routes"]:
        for s in r["stops"]:
            assert owners[s["orders"][0]["order_code"]] == r["rider_id"]
        mine = sorted(o["order_code"] for o in w.browsers[r["rider"]].get("/api/rider/orders").json())
        assert mine == sorted(o["order_code"] for s in r["stops"] for o in s["orders"])
    db.expire_all()
    plan_id = db.scalar(select(RoutePlan.id).where(RoutePlan.is_current.is_(True)))
    assert set(db.scalars(select(Assignment.plan_id)).all()) == {plan_id}


@pytest.mark.parametrize("vehicle,profile", [("scooter", "motor_scooter"), ("bike", "motorcycle")])
def test_single_profile_fleets_use_only_their_profile(app, admin, db, vehicle, profile):
    riders = [("rider_x", "Rider X", vehicle, 6, "office", "office", None),
              ("rider_y", "Rider Y", vehicle, 6, "warehouse", "warehouse", None)]
    w = make_world(app, admin, db, riders=riders)
    plan = plan_now(w)
    assert {p for p, _ in w.provider.calls} == {profile}
    assert plan["provenance"]["profile"].split(" ")[0] == profile
    for r in plan["routes"]:
        assert r["profile"] == profile and r["open_route"] is False
        assert r["road_distance_m"] == recorded_cost(profile, route_points(w, r))[0]


def test_mixed_fleet_prices_each_rider_with_their_own_profile(world):
    w = world
    plan = plan_now(w)
    assert {p for p, _ in w.provider.calls} == {"motor_scooter", "motorcycle"}
    for r in plan["routes"]:
        assert r["road_distance_m"] == recorded_cost(r["profile"], route_points(w, r))[0]
    # The two profiles really differ on these roads (Phase 0 evidence), so using the wrong one would show.
    pairs = RECORDINGS["motor_scooter"][1].keys()
    assert any(RECORDINGS["motor_scooter"][1][k].distance_m != RECORDINGS["motorcycle"][1][k].distance_m for k in pairs)


# ------------------------------------------------------------------ modes, locks, priority


def test_equal_mode_balances_counts_within_capacity(world):
    w = world
    set_mode(w, "equal")
    plan = plan_now(w)
    counts = sorted(len(r["stops"]) for r in plan["routes"])
    assert counts == [3, 4, 4] and plan["mode"] == "equal"


def test_equal_mode_explains_when_locks_make_equality_impossible(world):
    w = world
    set_mode(w, "equal")
    for code in ["RW-P001", "RW-P002", "RW-P003", "RW-P004", "RW-P005"]:
        assert lock(w, code, "Rider A").status_code == 200
    plan = plan_now(w)
    assert len(routes(plan)["Rider A"]["stops"]) == 5
    assert any(x.startswith("Equal target") and "Rider A" in x and "5 orders are locked" in x
               for x in plan["warnings"]), plan["warnings"]
    assert not any(len(x) == 36 and x.count("-") == 4 for x in plan["warnings"])  # names, not raw rider ids


def test_manual_mode_preserves_every_owner_and_optimizes_sequence(world):
    w = world
    set_mode(w, "manual")
    wanted = {}
    for i, code in enumerate(sorted(w.codes)):
        rider = ["Rider A", "Rider B", "Rider C"][i % 3]
        wanted[code] = rider
        assert lock(w, code, rider).status_code == 200
    plan = plan_now(w)
    got = {o["order_code"]: r["rider"] for r in plan["routes"] for s in r["stops"] for o in s["orders"]}
    assert got == wanted


def test_manual_mode_without_every_owner_is_refused_before_scheduling(world, db):
    w = world
    set_mode(w, "manual")
    lock(w, "RW-P001", "Rider A")
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "MANUAL_ASSIGNMENT_MISSING"
    assert "RW-P002" in r.json()["detail"]["details"] and run_count(db) == 0


def test_smart_mode_honours_locks(world):
    w = world
    lock(w, "RW-P011", "Rider A")  # Civil Lines: far from Rider A's natural area
    lock(w, "RW-P010", "Rider C")
    plan = plan_now(w)
    got = {o["order_code"]: r["rider"] for r in plan["routes"] for s in r["stops"] for o in s["orders"]}
    assert got["RW-P011"] == "Rider A" and got["RW-P010"] == "Rider C"


def test_first_delivery_priority_is_the_first_stop_of_its_route(world):
    w = world
    assert priority(w, "RW-P008").status_code == 200
    assert priority(w, "RW-P011").status_code == 200
    plan = plan_now(w)
    firsts = {r["stops"][0]["orders"][0]["order_code"] for r in plan["routes"] if r["stops"]}
    assert {"RW-P008", "RW-P011"} <= firsts


@pytest.mark.parametrize("case", ["same_rider", "more_than_riders"])
def test_priority_conflicts_are_explained_before_scheduling(world, db, case):
    w = world
    if case == "same_rider":
        for code in ("RW-P001", "RW-P002"):
            priority(w, code)
            lock(w, code, "Rider B")
    else:
        for code in ("RW-P001", "RW-P002", "RW-P003", "RW-P004"):
            priority(w, code)
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PRIORITY_CONFLICT"
    text_ = json.dumps(r.json())
    assert ("Rider B" in text_) if case == "same_rider" else ("4 first-priority" in text_)
    assert w.ids["Rider B"] not in text_ and run_count(db) == 0


def test_capacity_and_lock_infeasibility_are_coded(app, admin, db):
    riders = [("rider_x", "Rider X", "scooter", 4, "office", "last_stop", None),
              ("rider_y", "Rider Y", "bike", 4, "warehouse", "last_stop", None)]
    w = make_world(app, admin, db, riders=riders)
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INSUFFICIENT_CAPACITY"
    v = setup_of(w.browsers["Rider Y"], w.rid).json()["config_version"]
    put_rider(admin, w.rid, w.ids["Rider Y"], version=v, capacity=7)
    confirm(w.browsers["Rider Y"], w.rid)
    for code in ["RW-P001", "RW-P002", "RW-P003", "RW-P004", "RW-P005"]:
        lock(w, code, "Rider X")
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "LOCK_EXCEEDS_CAPACITY"
    assert "Rider X" in json.dumps(r.json()) and run_count(db) == 0


def test_lock_and_priority_validation(world, db):
    w = world
    o = orders_by_code(w)["RW-P001"]
    stranger = str(uuid.uuid4())
    r = w.admin.send("PUT", f"/api/admin/orders/{o['id']}/lock", json={"version": o["version"], "rider_id": stranger})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_LOCK"
    assert w.admin.send("PUT", f"/api/admin/orders/{o['id']}/lock",
                        json={"version": o["version"] + 5, "rider_id": None}).status_code == 409
    assert w.admin.send("PUT", f"/api/admin/orders/{o['id']}/priority",
                        json={"version": o["version"], "first_priority": "yes"}).status_code == 422
    assert w.admin.send("PUT", f"/api/admin/rounds/{w.rid}/mode", json={"mode": "balanced"}).status_code == 422
    r = lock(w, "RW-P001", "Rider A")
    assert r.json()["planning"]["locked_rider_id"] == w.ids["Rider A"] and r.json()["version"] == o["version"] + 1
    assert lock(w, "RW-P001", None).json()["planning"]["locked_rider_id"] is None


def test_bulk_lock_is_all_or_nothing(world, db):
    w = world
    orders = orders_by_code(w)
    body = {"rider_id": w.ids["Rider B"], "orders": [{"id": orders[c]["id"], "version": orders[c]["version"]}
                                                       for c in ("RW-P001", "RW-P002", "RW-P003")]}
    stale = json.loads(json.dumps(body))
    stale["orders"][1]["version"] += 1
    r = w.admin.send("POST", f"/api/admin/rounds/{w.rid}/locks", json=stale)
    assert r.status_code == 409 and r.json()["detail"]["details"] == ["RW-P002"]
    assert all(o["planning"]["locked_rider_id"] is None for o in orders_by_code(w).values())
    r = w.admin.send("POST", f"/api/admin/rounds/{w.rid}/locks", json=body)
    assert r.status_code == 200 and r.json()["changed"] == 3
    locked = {c for c, o in orders_by_code(w).items() if o["planning"]["locked_rider_id"] == w.ids["Rider B"]}
    assert locked == {"RW-P001", "RW-P002", "RW-P003"}
    dup = {"rider_id": None, "orders": [body["orders"][0], body["orders"][0]]}
    assert w.admin.send("POST", f"/api/admin/rounds/{w.rid}/locks", json=dup).status_code == 422
    other = {"rider_id": None, "orders": [{"id": str(uuid.uuid4()), "version": 1}]}
    assert w.admin.send("POST", f"/api/admin/rounds/{w.rid}/locks", json=other).status_code == 404


# ------------------------------------------------------------------ gates and invalid input


def test_unconfirmed_or_stale_confirmation_blocks_before_scheduling(world, db):
    w = world
    v = setup_of(w.browsers["Rider C"], w.rid).json()["config_version"]
    put_rider(w.admin, w.rid, w.ids["Rider C"], version=v, capacity=6)
    r = optimize(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_READY"
    assert any("Rider C" in d and "confirm" in d for d in r.json()["detail"]["details"]) and run_count(db) == 0
    choose(w.browsers["Rider C"], w.rid, "office")
    assert optimize(w).status_code == 409 and run_count(db) == 0
    confirm(w.browsers["Rider C"], w.rid)
    assert optimize(w).status_code == 202


def test_invalid_order_location_blocks_before_scheduling(world, db):
    w = world
    db.execute(update(Order).where(Order.order_code == "RW-P003")
               .values(location_state="needs_correction", lat=None, lng=None, location_source=None))
    db.commit()
    r = optimize(w)
    assert r.status_code == 409 and "RW-P003: location needs correction" in r.json()["detail"]["details"]
    assert run_count(db) == 0


def test_round_too_large_is_refused_with_the_limits(world, db, app):
    w = world
    s = app.state.settings
    app.state.planning.limits = replace(s.planning, max_pending_orders=5)
    app.state.settings = replace(s, planning=app.state.planning.limits)
    try:
        r = optimize(w)
    finally:
        app.state.settings = s
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ROUND_TOO_LARGE"
    assert "11 Pending orders" in r.json()["detail"]["message"] and run_count(db) == 0


def test_missing_tiles_are_reported_clearly_and_nothing_is_queued(world, db, app):
    w = world
    service = app.state.planning
    service.provider_override = None
    service.settings = replace(service.settings, valhalla_tiles=service.settings.valhalla_tiles / "missing")
    r = optimize(w)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ROUTING_ENGINE_UNAVAILABLE"
    assert "tiles" in r.json()["detail"]["message"] and "/" not in r.json()["detail"]["message"].split("(")[0][-3:]
    assert run_count(db) == 0


# ------------------------------------------------------------------ missing roads and provider failures


def test_missing_road_edges_are_never_used(app, admin, db):
    blocked = {("warehouse", "srcc", None), ("srcc", "daulat_ram", None), ("office", "kirori_mal", None)}
    w = make_world(app, admin, db, provider=RecordedDUProvider(missing=blocked))
    plan = plan_now(w)
    for r in plan["routes"]:
        path = route_points(w, r)
        assert not any((a, b, None) in blocked for a, b in zip(path, path[1:])), path
    assert sorted(all_codes(plan)) == sorted(w.codes)


def test_an_isolated_order_pin_fails_with_codes_and_nothing_is_dropped(app, admin, db):
    w = make_world(app, admin, db, points=["kirori_mal", "hindu_college", "daulat_ram_centroid"])
    run = wait_run(w, optimize(w).json()["id"])
    assert run["state"] == "failed" and run["error"]["code"] == "UNROUTABLE_LOCATION"
    assert run["error"]["details"] == ["RW-P003"]
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").status_code == 404


def test_an_isolated_home_destination_names_the_rider_not_the_place(app, admin, db):
    riders = [("rider_a", "Rider A", "scooter", 6, "office", "home", "daulat_ram_centroid"),
              ("rider_b", "Rider B", "bike", 6, "warehouse", "last_stop", None)]
    w = make_world(app, admin, db, riders=riders)
    run = wait_run(w, optimize(w).json()["id"])
    assert run["state"] == "failed" and run["error"]["code"] == "UNROUTABLE_ENDPOINT"
    assert run["error"]["details"] == ["Rider A: destination"]
    c = PUBLIC_DU["daulat_ram_centroid"]
    assert str(c["lat"]) not in json.dumps(run) and str(c["lng"]) not in json.dumps(run)


def test_provider_failure_keeps_the_previous_plan_and_assignments(world, db):
    w = world
    first = plan_now(w)
    owners = {c: o["planning"]["assigned_rider_id"] for c, o in orders_by_code(w).items()}
    w.provider.fail = True
    run = wait_run(w, optimize(w).json()["id"])
    assert run["state"] == "failed" and run["error"]["code"] == "ROUTING_ENGINE_UNAVAILABLE"
    assert "previous plan is unchanged" in run["error"]["message"]
    now = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert now["version"] == first["version"] == 1 and now["is_current"]
    assert {c: o["planning"]["assigned_rider_id"] for c, o in orders_by_code(w).items()} == owners


def test_a_matrix_without_real_road_provenance_is_never_saved(app, admin, db):
    w = make_world(app, admin, db, provider=RecordedDUProvider(synthetic=True))
    run = wait_run(w, optimize(w).json()["id"])
    assert run["state"] == "failed" and run["error"]["code"] == "NOT_ROAD_DISTANCES"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(RoutePlan)) == 0


# ------------------------------------------------------------------ statuses: Completed history, Postponed ownership


def test_replanning_preserves_completed_history_and_postponed_ownership(world, db):
    w = world
    first = plan_now(w)
    owner = {o["order_code"]: r["rider"] for r in first["routes"] for s in r["stops"] for o in s["orders"]}
    done, later = "RW-P001", "RW-P009"
    set_status(w, done, "Completed")
    set_status(w, later, "Postponed")
    plan = plan_now(w)
    assert plan["version"] == 2
    rs = routes(plan)
    assert [o["order_code"] for o in rs[owner[done]]["completed"]] == [done]
    assert [o["order_code"] for o in rs[owner[later]]["postponed"]] == [later]
    assert done not in all_codes(plan) and later not in all_codes(plan)  # off the active sequence
    assert sorted(all_codes(plan)) == sorted(set(w.codes) - {done, later})
    assert plan["summary"]["completed_held"] == 1 and plan["summary"]["postponed_held"] == 1
    owners = {c: o["planning"]["assigned_rider_id"] for c, o in orders_by_code(w).items()}
    assert owners[done] == w.ids[owner[done]] and owners[later] == w.ids[owner[later]]
    statuses = {c: o["status"] for c, o in orders_by_code(w).items()}
    assert statuses[done] == "Completed" and statuses[later] == "Postponed"  # never reset
    # Held orders count toward capacity: no route carries more than its rider's capacity.
    for r in plan["routes"]:
        assert sum(len(s["orders"]) for s in r["stops"]) + len(r["postponed"]) + len(r["completed"]) <= r["capacity"]


def test_reassigning_a_postponed_or_completed_order_is_explicitly_unsupported(world, db):
    w = world
    first = plan_now(w)
    owner = {o["order_code"]: r["rider"] for r in first["routes"] for s in r["stops"] for o in s["orders"]}
    set_status(w, "RW-P002", "Postponed")
    set_status(w, "RW-P003", "Completed")
    for code in ("RW-P002", "RW-P003"):
        other = next(n for n in w.ids if n != owner[code])
        before = orders_by_code(w)[code]
        r = lock(w, code, other)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "OWNERSHIP_CHANGE_UNSUPPORTED"
        assert orders_by_code(w)[code] == before  # unchanged
        assert lock(w, code, owner[code]).status_code == 200  # locking to the current owner is fine
    # A lock that disagrees with the owner (e.g. set while Pending) is caught before scheduling.
    db.execute(update(Order).where(Order.order_code == "RW-P002")
               .values(locked_rider_id=uuid.UUID(w.ids[next(n for n in w.ids if n != owner["RW-P002"])])))
    db.commit()
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "OWNERSHIP_CHANGE_UNSUPPORTED"
    assert r.json()["detail"]["details"] == ["RW-P002"]
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()["version"] == 1


def test_postponed_without_owner_is_unsupported_and_left_unchanged(world, db):
    w = world
    set_status(w, "RW-P004", "Postponed")
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "POSTPONED_WITHOUT_OWNER"
    assert r.json()["detail"]["details"] == ["RW-P004"] and "Pending" in r.json()["detail"]["message"]
    assert orders_by_code(w)["RW-P004"]["status"] == "Postponed" and run_count(db) == 0


def test_postponed_owned_by_a_removed_rider_is_unsupported(world, db):
    w = world
    first = plan_now(w)
    owner = {o["order_code"]: r["rider"] for r in first["routes"] for s in r["stops"] for o in s["orders"]}
    code = next(c for c, n in owner.items() if n == "Rider B")
    set_status(w, code, "Postponed")
    v = setup_of(w.browsers["Rider B"], w.rid).json()["config_version"]
    put_rider(w.admin, w.rid, w.ids["Rider B"], version=v, participating=False)
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "OWNER_NOT_PARTICIPATING"
    assert r.json()["detail"]["details"] == [code]
    assert orders_by_code(w)[code]["planning"]["assigned_rider_id"] == w.ids["Rider B"]


def test_completed_orders_without_owner_or_with_a_removed_owner_stay_history(world, db):
    w = world
    set_status(w, "RW-P005", "Completed")  # completed before any plan: no owner
    assert lock(w, "RW-P006", "Rider C").status_code == 200  # so Rider C certainly owns an order
    first = plan_now(w)
    assert first["summary"]["completed_without_owner"] == ["RW-P005"]
    assert "RW-P005" not in all_codes(first)
    assert orders_by_code(w)["RW-P005"]["planning"]["assigned_rider_id"] is None
    code = "RW-P006"
    set_status(w, code, "Completed")
    v = setup_of(w.browsers["Rider C"], w.rid).json()["config_version"]
    put_rider(w.admin, w.rid, w.ids["Rider C"], version=v, participating=False)
    # Rider C's remaining Pending orders move to A/B (capacity permitting); C's completed order stays C's.
    v_b = setup_of(w.browsers["Rider B"], w.rid).json()["config_version"]
    put_rider(w.admin, w.rid, w.ids["Rider B"], version=v_b, capacity=8)
    confirm(w.browsers["Rider B"], w.rid)
    plan = plan_now(w)
    assert code in plan["summary"]["completed_owner_not_participating"]
    assert orders_by_code(w)[code]["planning"]["assigned_rider_id"] == w.ids["Rider C"]


def test_priority_only_on_pending_orders(world):
    w = world
    set_status(w, "RW-P006", "Postponed")
    r = priority(w, "RW-P006")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PRIORITY_NOT_PENDING"
    assert priority(w, "RW-P006", False).status_code == 200


# ------------------------------------------------------------------ versions, history, out of date


def test_plan_history_and_out_of_date(world, clock):
    w = world
    v1 = plan_now(w)
    clock.advance(minutes=5)  # runs are listed newest first by request time
    order = orders_by_code(w)["RW-P002"]
    w.admin.send("PATCH", f"/api/admin/orders/{order['id']}",
                 json={"version": order["version"], "customer_name": "Test Customer Renamed"})
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()["out_of_date"] is False  # text is not input
    order = orders_by_code(w)["RW-P002"]
    w.admin.send("POST", f"/api/admin/orders/{order['id']}/pin", json={"version": order["version"], **{
        "lat": PUBLIC_DU["ramjas"]["lat"], "lng": PUBLIC_DU["ramjas"]["lng"]}})
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()["out_of_date"] is True
    w.codes["RW-P002"] = "ramjas"
    v2 = plan_now(w)
    assert (v1["version"], v2["version"]) == (1, 2) and not v2["out_of_date"]
    history = w.admin.get(f"/api/admin/rounds/{w.rid}/plans").json()
    assert [(p["version"], p["is_current"]) for p in history] == [(2, True), (1, False)]
    old = w.admin.get(f"/api/admin/rounds/{w.rid}/plans/1").json()
    assert old["is_current"] is False and old["superseded_at"] and old["out_of_date"] is True
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plans/9").status_code == 404
    runs = w.admin.get(f"/api/admin/rounds/{w.rid}/planning-runs").json()
    assert [r["plan_version"] for r in runs] == [2, 1] and all(r["state"] == "succeeded" for r in runs)
    set_mode(w, "equal")
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()["out_of_date"] is True


def test_replanning_reports_ownership_changes(world):
    w = world
    v1 = plan_now(w)
    set_mode(w, "equal")
    v2 = plan_now(w)
    owner1 = {o["order_code"]: r["rider"] for r in v1["routes"] for s in r["stops"] for o in s["orders"]}
    owner2 = {o["order_code"]: r["rider"] for r in v2["routes"] for s in r["stops"] for o in s["orders"]}
    moved = sorted(c for c in owner1 if owner1[c] != owner2[c])
    assert sorted(c["order_code"] for c in v2["summary"]["ownership_changes"]) == moved
    for c in v2["summary"]["ownership_changes"]:
        assert (c["from_rider"], c["to_rider"]) == (owner1[c["order_code"]], owner2[c["order_code"]])


def test_database_enforces_one_current_plan_and_one_owner_per_plan(world, db):
    w = world
    plan_now(w)
    plan_now(w)
    for sql in ("UPDATE route_plans SET is_current = true",
                "INSERT INTO plan_orders (plan_id, order_id, rider_id, role, stop_seq) "
                "SELECT plan_id, order_id, rider_id, role, stop_seq FROM plan_orders LIMIT 1",
                "UPDATE plan_orders SET stop_seq = NULL WHERE role = 'active'",
                "UPDATE plan_routes SET profile = 'bicycle'",
                "UPDATE plan_routes SET profile = 'motorcycle' WHERE vehicle = 'scooter'",
                "UPDATE plan_routes SET open_route = NOT open_route",
                "UPDATE delivery_rounds SET mode = 'balanced'",
                "UPDATE planning_runs SET state = 'queued'"):
        with pytest.raises(IntegrityError):
            db.execute(text(sql))
            db.commit()
        db.rollback()


# ------------------------------------------------------------------ privacy


def test_no_destination_coordinates_in_plans_runs_errors_or_logs(app, admin, db, caplog):
    caplog.set_level(logging.DEBUG)
    riders = [("rider_a", "Rider A", "scooter", 6, "office", "home", "home_r1"),
              ("rider_b", "Rider B", "bike", 6, "warehouse", "custom", "custom_r2")]
    w = make_world(app, admin, db, riders=riders)
    plan = plan_now(w)
    responses = [json.dumps(plan), w.admin.get(f"/api/admin/rounds/{w.rid}/planning-runs").text,
                 w.admin.get(f"/api/admin/rounds/{w.rid}/plans").text,
                 w.admin.get(f"/api/admin/rounds/{w.rid}/orders").text]
    w.provider.fail = True
    responses.append(json.dumps(wait_run(w, optimize(w).json()["id"])))
    for body in responses:
        assert not any(s in body for s in PRIVATE)
    db.expire_all()
    stored = json.dumps([p.provenance for p in db.scalars(select(RoutePlan)).all()])
    assert not any(s in stored for s in PRIVATE)
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert not any(s in logs for s in PRIVATE) and "Test Customer" not in logs


def test_equal_warning_says_when_the_bounded_search_rather_than_locks_missed_the_band():
    from routewise_api.planning import _explain_equal
    from routewise_api.routing import domain as d

    rnd = d.DeliveryRound("r", d.Depots("a", "b"), [], [d.Order("O1", "L1", locked_rider_id="Rider A")], {})
    msg = _explain_equal("equal target 9-10 not met for Rider B (12) due to locks/grouping", rnd)
    assert msg.startswith("Equal target 9–10 orders not met for Rider B: 12 orders.")
    assert "time-bounded search did not reach it" in msg and "locks/grouping" not in msg
    assert _explain_equal("solver status X", rnd) == "solver status X"


def test_held_orders_use_up_their_riders_capacity(app, admin, db):
    riders = [("rider_x", "Rider X", "scooter", 2, "office", "last_stop", None),
              ("rider_y", "Rider Y", "bike", 12, "warehouse", "last_stop", None)]
    w = make_world(app, admin, db, riders=riders)
    for code in ("RW-P001", "RW-P002"):
        assert lock(w, code, "Rider X").status_code == 200
    plan_now(w)
    set_status(w, "RW-P001", "Postponed")
    set_status(w, "RW-P002", "Completed")
    assert lock(w, "RW-P003", "Rider X").status_code == 200  # Rider X already holds 2 of 2
    r = optimize(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "LOCK_EXCEEDS_CAPACITY"
    assert lock(w, "RW-P003", None).status_code == 200
    plan = plan_now(w)
    x = routes(plan)["Rider X"]
    assert x["stops"] == [] and len(x["postponed"]) == 1 and len(x["completed"]) == 1
