"""Step 3B: a rider's own delivery-status updates, against real PostgreSQL.

Covers the permitted transitions, ownership and CSRF, version conflicts and repeats, races with
admin edits and with plan commits, and the route-validity rule: a rider's own progress makes
in-flight solves stale but leaves every rider's remaining saved sequence usable, while any other
planning-input change still marks the plan out of date. Orders are synthetic customers on public
DU North Campus OSM points; road costs are the recorded real local-Valhalla matrices."""

import logging
import threading
import uuid

import pytest
from sqlalchemy import create_engine, select

from routewise_api.models import Assignment, DeliveryRound, Order, RoutePlan

from .conftest import Browser
from .planning_world import PUBLIC_DU, optimize, orders_by_code, plan_now, wait_run
from .planning_world import world  # noqa: F401  (fixture)
from .test_concurrency import _wait_for_lock_waiters
from .test_planning import PRIVATE, routes, set_status
from .test_planning_concurrency import Gate, Pause, _edit_committed_or_blocked, hold
from .test_rider_deliveries import all_items, deliveries, seq_codes
from .test_round_setup import choose, put_rider, set_depot, setup_of


def post_status(b, order_id, status, version, **kw):
    return b.send("POST", f"/api/rider/orders/{order_id}/status", json={"status": status, "expected_version": version}, **kw)


def item(view, code):
    return next(o for o in all_items(view) if o["order_code"] == code)


def mine(w, name, plan=None):
    """(rider browser, the codes of their saved route in order)."""
    plan = plan or w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    return w.browsers[name], [o["order_code"] for s in routes(plan)[name]["stops"] for o in s["orders"]]


def update(w, name, code, status, *, expect=200):
    b = w.browsers[name]
    o = item(deliveries(b, w.rid).json(), code)
    r = post_status(b, o["id"], status, o["version"])
    assert r.status_code == expect, r.text
    return r.json()


def round_versions(db, rid):
    db.expire_all()
    rnd = db.get(DeliveryRound, uuid.UUID(rid))
    return rnd.input_version, rnd.route_version


# ------------------------------------------------------------------ transitions


def test_permitted_transitions_move_the_order_and_completed_is_final(world, db):
    w = world
    plan = plan_now(w)
    b, codes = mine(w, "Rider A", plan)
    first, second = codes[0], codes[1]
    seqs = {o["order_code"]: s["seq"] for s in routes(plan)["Rider A"]["stops"] for o in s["orders"]}

    body = update(w, "Rider A", first, "Postponed")
    assert body["changed"] is True and body["order"]["status"] == "Postponed"
    view = body["view"]
    assert [o["order_code"] for o in view["postponed"]] == [first]
    assert seq_codes(view) == codes[1:]  # the others keep their relative order
    assert view["sequence"][0]["orders"][0]["order_code"] == second  # the next Pending stop moved on

    body = update(w, "Rider A", first, "Pending")  # explicit return: back at its saved position
    assert seq_codes(body["view"]) == codes and body["view"]["postponed"] == []
    assert {o["order_code"]: s["seq"] for s in body["view"]["sequence"] for o in s["orders"]} == seqs

    body = update(w, "Rider A", first, "Completed")
    assert [o["order_code"] for o in body["view"]["completed"]] == [first] and seq_codes(body["view"]) == codes[1:]
    done = item(body["view"], first)
    for target in ("Pending", "Postponed"):  # a rider cannot reopen a Completed order
        r = post_status(b, done["id"], target, done["version"])
        assert r.status_code == 422 and r.json()["detail"]["code"] == "transition_not_allowed"
        assert "cannot be reopened" in r.json()["detail"]["message"]
    update(w, "Rider A", second, "Postponed")
    o = item(deliveries(b, w.rid).json(), second)
    r = post_status(b, o["id"], "Completed", o["version"])  # Postponed → Completed needs Pending first
    assert r.status_code == 422 and r.json()["detail"]["code"] == "transition_not_allowed"
    db.expire_all()
    statuses = dict(db.execute(select(Order.order_code, Order.status).where(Order.order_code.in_([first, second]))).all())
    assert statuses == {first: "Completed", second: "Postponed"}
    # Ownership is unchanged by postponing and returning.
    owner = dict(db.execute(select(Order.order_code, Assignment.rider_id).join(Assignment, Assignment.order_id == Order.id)
                            .where(Order.order_code.in_([first, second]))).all())
    assert {str(v) for v in owner.values()} == {w.ids["Rider A"]}


@pytest.mark.parametrize("payload", [
    {"status": "Delivered", "expected_version": 1}, {"status": "pending", "expected_version": 1},
    {"status": "Completed"}, {"status": "Completed", "expected_version": "1"}, {"status": None, "expected_version": 1},
], ids=["unknown", "lowercase", "no-version", "string-version", "null"])
def test_invalid_statuses_and_payloads_are_rejected(world, db, payload):
    w = world
    plan_now(w)
    b, codes = mine(w, "Rider A")
    o = item(deliveries(b, w.rid).json(), codes[0])
    r = b.send("POST", f"/api/rider/orders/{o['id']}/status", json=payload)
    assert r.status_code == 422
    db.expire_all()
    assert db.scalar(select(Order.status).where(Order.order_code == codes[0])) == "Pending"


# ------------------------------------------------------------------ ownership, CSRF, direct ids


def test_only_the_owner_can_change_an_order_and_others_learn_nothing(world, db, browser):
    w = world
    plan_now(w)
    _, codes = mine(w, "Rider A")
    target = item(deliveries(w.browsers["Rider A"], w.rid).json(), codes[0])
    other = w.browsers["Rider B"]
    foreign = post_status(other, target["id"], "Completed", target["version"])
    missing = post_status(other, uuid.uuid4(), "Completed", 1)
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
    assert "Test Customer" not in foreign.text
    assert post_status(other, "not-a-uuid", "Completed", 1).status_code == 422
    assert w.admin.send("POST", f"/api/rider/orders/{target['id']}/status",
                        json={"status": "Completed", "expected_version": target["version"]}).status_code == 403
    assert browser().send("POST", f"/api/rider/orders/{target['id']}/status",
                          json={"status": "Completed", "expected_version": target["version"]}).status_code == 401
    owner = w.browsers["Rider A"]
    no_csrf = post_status(owner, target["id"], "Completed", target["version"], csrf=False)
    bad_origin = post_status(owner, target["id"], "Completed", target["version"], origin="https://evil.example")
    assert no_csrf.status_code == 403 and bad_origin.status_code == 403
    db.expire_all()
    assert db.scalar(select(Order.status).where(Order.order_code == codes[0])) == "Pending"


# ------------------------------------------------------------------ versions, repeats, races


def test_stale_versions_never_overwrite_newer_work_or_reopen_completed(world, db):
    w = world
    plan_now(w)
    b, codes = mine(w, "Rider A")
    seen = item(deliveries(b, w.rid).json(), codes[0])
    o = orders_by_code(w)[codes[0]]
    assert w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "product": "Renamed"}).status_code == 200
    r = post_status(b, seen["id"], "Completed", seen["version"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "order_changed"
    assert r.json()["detail"]["current_version"] == seen["version"] + 1 and r.json()["detail"]["current_status"] == "Pending"
    set_status(w, codes[0], "Completed")  # the admin completes it
    r = post_status(b, seen["id"], "Postponed", seen["version"])  # a stale request cannot undo it
    assert r.status_code == 409 and r.json()["detail"]["current_status"] == "Completed"
    db.expire_all()
    assert db.scalar(select(Order.status).where(Order.order_code == codes[0])) == "Completed"


def test_repeated_submissions_change_nothing_twice(world, db):
    w = world
    plan_now(w)
    b, codes = mine(w, "Rider A")
    o = item(deliveries(b, w.rid).json(), codes[0])
    first = post_status(b, o["id"], "Completed", o["version"])
    assert first.status_code == 200 and first.json()["changed"] is True
    versions = round_versions(db, w.rid)
    for _ in range(2):  # a retry or a double tap carries the same, now old, version
        again = post_status(b, o["id"], "Completed", o["version"])
        assert again.status_code == 200 and again.json()["changed"] is False
        assert again.json()["order"]["version"] == o["version"] + 1
    assert round_versions(db, w.rid) == versions  # no extra planning-input revision


def _race(db_url, order_id, calls):
    """Hold the order row, start every call, wait until all block on it, release, collect."""
    engine, conn, tx = hold(db_url, "SELECT 1 FROM orders WHERE id = :id FOR UPDATE", {"id": order_id})
    results = [None] * len(calls)
    threads = [threading.Thread(target=lambda i=i, c=c: results.__setitem__(i, c())) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    try:
        _wait_for_lock_waiters(engine, len(calls))
    finally:
        tx.rollback()
        conn.close()
    for t in threads:
        t.join(30)
    engine.dispose()
    return results


def test_concurrent_updates_from_two_tabs_have_exactly_one_winner(world, db, db_url, app):
    w = world
    plan_now(w)
    b, codes = mine(w, "Rider A")
    second_tab = Browser(app)
    assert second_tab.login("rider_a").status_code == 200
    o = item(deliveries(b, w.rid).json(), codes[0])
    results = _race(db_url, o["id"], [lambda: post_status(b, o["id"], "Completed", o["version"]),
                                      lambda: post_status(second_tab, o["id"], "Postponed", o["version"])])
    codes_ = sorted(r.status_code for r in results)
    assert codes_ == [200, 409], [r.text for r in results]
    winner = next(r for r in results if r.status_code == 200).json()["order"]["status"]
    loser = next(r for r in results if r.status_code == 409).json()["detail"]
    assert loser["code"] == "order_changed" and loser["current_status"] == winner
    db.expire_all()
    row = db.scalar(select(Order).where(Order.order_code == codes[0]))
    assert row.status == winner and row.version == o["version"] + 1


def test_an_admin_edit_racing_a_rider_update_has_exactly_one_winner(world, db, db_url):
    w = world
    plan_now(w)
    b, codes = mine(w, "Rider A")
    o = item(deliveries(b, w.rid).json(), codes[0])
    admin_o = orders_by_code(w)[codes[0]]
    results = _race(db_url, o["id"], [
        lambda: post_status(b, o["id"], "Completed", o["version"]),
        lambda: w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": admin_o["version"], "status": "Postponed"})])
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    db.expire_all()
    row = db.scalar(select(Order).where(Order.order_code == codes[0]))
    assert row.version == o["version"] + 1 and row.status in ("Completed", "Postponed")


# ------------------------------------------------------------------ route validity


def test_delivery_progress_keeps_every_saved_route_usable_and_totals_as_planned(world, db):
    w = world
    plan = plan_now(w)
    total = plan["summary"]["total_road_distance_m"]
    before = {name: mine(w, name, plan)[1] for name in w.browsers}
    _, a_codes = mine(w, "Rider A", plan)
    input_before, route_before = round_versions(db, w.rid)
    update(w, "Rider A", a_codes[0], "Completed")
    update(w, "Rider A", a_codes[1], "Postponed")
    input_after, route_after = round_versions(db, w.rid)
    assert input_after == input_before + 2 and route_after == route_before  # input revised, route still usable
    for name, codes in before.items():
        view = deliveries(w.browsers[name], w.rid).json()
        assert view["plan"]["out_of_date"] is False and view["plan"]["progress_since_plan"] is True
        expected = [c for c in codes if c not in a_codes[:2]]
        assert seq_codes(view) == expected  # relative order unchanged for everyone
    current = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert current["out_of_date"] is False and current["progress_since_plan"] is True and current["unplanned_pending"] == []
    assert current["summary"]["total_road_distance_m"] == total and current["version"] == 1  # history untouched
    history = w.admin.get(f"/api/admin/rounds/{w.rid}/plans").json()
    assert history[0]["out_of_date"] is False and history[0]["progress_since_plan"] is True
    db.expire_all()
    p = db.scalar(select(RoutePlan).where(RoutePlan.round_id == uuid.UUID(w.rid)))
    assert (p.input_version, p.route_version) == (input_before, route_before)  # never rewritten to look current


def _pin(w):
    o = orders_by_code(w)["RW-P004"]
    return w.admin.send("POST", f"/api/admin/orders/{o['id']}/pin",
                        json={"version": o["version"], "lat": PUBLIC_DU["ramjas"]["lat"], "lng": PUBLIC_DU["ramjas"]["lng"]})


def _admin_status(w):
    o = orders_by_code(w)["RW-P004"]
    return w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": "Postponed"})


def _destination(w):
    return choose(w.browsers["Rider C"], w.rid, "office")


def _capacity(w):
    v = setup_of(w.browsers["Rider A"], w.rid).json()["config_version"]
    return put_rider(w.admin, w.rid, w.ids["Rider A"], version=v, capacity=6)


def _depot(w):
    office = w.admin.get("/api/admin/depots").json()["office"]
    return set_depot(w.admin, "office", PUBLIC_DU["gtb_nagar"], version=office["version"])


def _mode(w):
    return w.admin.send("PUT", f"/api/admin/rounds/{w.rid}/mode", json={"mode": "equal"})


def _lock(w):
    o = orders_by_code(w)["RW-P004"]
    return w.admin.send("PUT", f"/api/admin/orders/{o['id']}/lock", json={"version": o["version"], "rider_id": w.ids["Rider B"]})


@pytest.mark.parametrize("change", [_pin, _admin_status, _destination, _capacity, _depot, _mode, _lock],
                         ids=lambda f: f.__name__.strip("_"))
def test_genuine_changes_after_progress_still_mark_the_plan_out_of_date(world, change):
    w = world
    plan_now(w)
    _, codes = mine(w, "Rider A")
    update(w, "Rider A", codes[0], "Completed")
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()["out_of_date"] is False
    assert change(w).status_code == 200
    current = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert current["out_of_date"] is True and current["progress_since_plan"] is False
    for b in w.browsers.values():
        assert deliveries(b, w.rid).json()["plan"]["out_of_date"] is True


def test_returning_to_pending_reuses_only_a_saved_position(world, db):
    w = world
    # Postponed BEFORE planning: the plan holds it as postponed, with no route position.
    o = orders_by_code(w)["RW-P001"]
    assert w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": "Postponed"}).status_code == 200
    db.execute(Assignment.__table__.insert().values(order_id=uuid.UUID(o["id"]), rider_id=uuid.UUID(w.ids["Rider A"])))
    db.commit()
    plan = plan_now(w)
    assert "RW-P001" in [x["order_code"] for x in routes(plan)["Rider A"]["postponed"]]
    body = update(w, "Rider A", "RW-P001", "Pending")
    view = body["view"]
    assert [x["order_code"] for x in view["unsequenced"]] == ["RW-P001"]  # needs planning; no invented position
    assert "RW-P001" not in seq_codes(view) and view["plan"]["out_of_date"] is False
    current = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert current["unplanned_pending"] == ["RW-P001"] and current["out_of_date"] is False
    db.expire_all()
    assert str(db.scalar(select(Assignment.rider_id).where(Assignment.order_id == uuid.UUID(o["id"])))) == w.ids["Rider A"]
    # Re-planning includes it again.
    assert "RW-P001" in [c for name in w.browsers for c in mine(w, name, plan_now(w))[1]]


# ------------------------------------------------------------------ races with planning


def test_a_rider_update_during_a_solve_makes_the_run_stale(world, db, app):
    w = world
    plan_now(w)
    _, codes = mine(w, "Rider A")
    before = {c: o["planning"]["assigned_rider_id"] for c, o in orders_by_code(w).items()}
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    update(w, "Rider A", codes[0], "Completed")
    pause.go.set()
    run = wait_run(w, run_id)
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    current = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert current["version"] == 1 and current["out_of_date"] is False  # the saved route is still usable
    assert {c: o["planning"]["assigned_rider_id"] for c, o in orders_by_code(w).items()} == before


def test_a_replan_moving_the_order_wins_over_the_former_owners_update(world, db, db_url, app):
    """The commit has passed its final check and holds the round lock; the plan gives the order to
    Rider B. Rider A's update for that order waits for the round, then re-checks ownership and is
    refused: the former owner's change never slips through."""
    w = world
    plan_now(w)
    b, codes = mine(w, "Rider A")
    moving = codes[0]
    o = orders_by_code(w)[moving]
    assert w.admin.send("PUT", f"/api/admin/orders/{o['id']}/lock",
                        json={"version": o["version"], "rider_id": w.ids["Rider B"]}).status_code == 200
    seen = item(deliveries(b, w.rid).json(), moving)  # Rider A still owns it and sees its current version
    gate = Gate(app.state.planning)
    run_id = optimize(w).json()["id"]
    assert gate.reached.wait(60), "worker never reached the final check"
    result = {}
    rider = threading.Thread(target=lambda: result.setdefault("r", post_status(b, seen["id"], "Completed", seen["version"])))
    rider.start()
    engine = create_engine(db_url)
    try:
        first = _edit_committed_or_blocked(engine, rider)
    finally:
        gate.go.set()
        engine.dispose()
    rider.join(30)
    assert not first, "the rider update did not wait for the plan commit"
    assert wait_run(w, run_id)["state"] == "succeeded"
    r = result["r"]
    assert r.status_code == 409 and r.json()["detail"]["code"] == "order_reassigned"
    assert "current_status" not in r.json()["detail"]
    db.expire_all()
    row = db.scalar(select(Order).where(Order.order_code == moving))
    assert row.status == "Pending"
    assert str(db.scalar(select(Assignment.rider_id).where(Assignment.order_id == row.id))) == w.ids["Rider B"]
    assert moving in seq_codes(deliveries(w.browsers["Rider B"], w.rid).json())
    assert moving not in {x["order_code"] for x in all_items(deliveries(b, w.rid).json())}


def test_status_updates_log_no_customer_fields(world, caplog):
    caplog.set_level(logging.DEBUG)
    w = world
    plan_now(w)
    _, codes = mine(w, "Rider A")
    update(w, "Rider A", codes[0], "Postponed")
    update(w, "Rider A", codes[0], "Pending")
    update(w, "Rider A", codes[0], "Completed")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Test Customer" not in text and "Synthetic parcel" not in text and "0000000" not in text
    for s in PRIVATE:
        assert s not in text
