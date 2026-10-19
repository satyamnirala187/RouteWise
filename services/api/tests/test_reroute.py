"""Step 4B: a rider's own reroute (rider route revisions on immutable round plans), against real
PostgreSQL with the recorded real local-Valhalla DU matrices.

Covers: only the rider's own Pending orders are re-sequenced and nothing else is written (rows of
other riders, plan rows and assignments compared before/after); explicit, honest origins (current
position, last completed stop, configured start) and device-fix validation; trustworthy completion
records; rider-only destination invalidation and recalculation after confirmation (R23); vehicle
profile, priority, held capacity and Last-stop open routes; bounded single-run-per-rider work;
races with the rider's own and other riders' status changes, configuration and account changes,
ownership changes, admin replanning and the final commit; and that no device position is stored.

Customers are synthetic; locations are public OSM points; the "device position" is the public
fixture point gps_r1 (mocked; no device is involved)."""

import json
import logging
import threading
import time
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select, text

from routewise_api import accounts
from routewise_api.config import load_settings
from routewise_api.models import Order, PlanningRun, RouteRevision, User
from routewise_api.planning import recover_interrupted_runs

from .planning_world import PUBLIC_DU, orders_by_code, plan_now, recorded_cost, wait_run
from .planning_world import world  # noqa: F401  (fixture)
from .test_planning import lock, priority, routes
from .test_planning_concurrency import _edit_committed_or_blocked
from .test_rider_deliveries import deliveries, seq_codes
from .test_rider_status import item, post_status, update
from .test_round_setup import choose, confirm, put_rider, setup_of

GPS = PUBLIC_DU["gps_r1"]
GPS_STRINGS = [str(GPS["lat"]), str(GPS["lng"])]
TERMINAL = {"succeeded", "failed", "stale", "interrupted"}


def gps(**kw):
    return {"kind": "current_position", "lat": GPS["lat"], "lng": GPS["lng"], "accuracy_m": 25, "age_s": 5, **kw}


def planned(w):
    """Lock four orders to Rider A (smart mode honours locks) so A has a real sequence (at least
    four stops; smart mode may add more), then plan."""
    for code in ("RW-P001", "RW-P002", "RW-P003", "RW-P005"):
        assert lock(w, code, "Rider A").status_code == 200
    return plan_now(w)


def codes_of(w, name):
    plan = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    return [o["order_code"] for s in routes(plan)[name]["stops"] for o in s["orders"]]


def ask(w, name, origin, *, plan_version=None, revision=None):
    b = w.browsers[name]
    view = deliveries(b, w.rid).json()
    pv = view["plan"]["version"] if plan_version is None else plan_version
    rev = (view["plan"]["rider_route"]["revision"] or {}).get("number", 0) if revision is None else revision
    return b.send("POST", f"/api/rider/rounds/{w.rid}/reroute",
                  json={"origin": origin, "expected_plan_version": pv, "expected_revision": rev})


def wait_reroute(w, name, run_id, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        run = w.browsers[name].get(f"/api/rider/reroutes/{run_id}").json()
        if run["state"] in TERMINAL:
            return run
        time.sleep(0.05)
    raise AssertionError("reroute did not finish")


def reroute_now(w, name, origin, expect="succeeded"):
    r = ask(w, name, origin)
    assert r.status_code == 202, r.text
    run = wait_reroute(w, name, r.json()["id"])
    assert run["state"] == expect, run
    return run


def code(r):
    return r.json()["detail"]["code"]


def frozen_rows(db, except_rider=None) -> dict:
    """Every planning row a reroute must never change, as text (another rider's rows; all plan rows
    and assignments). Revisions of `except_rider` are excluded (the requesting rider's own)."""
    db.expire_all()
    rows = {}
    with db.bind.connect() as conn:
        for table in ("route_plans", "plan_routes", "plan_orders", "assignments", "orders", "round_riders",
                      "rider_endpoints"):
            rows[table] = sorted(r[0] for r in conn.execute(text(f"SELECT t::text FROM {table} t")))
        rows["route_revisions"] = sorted(r[0] for r in conn.execute(
            text("SELECT t::text FROM route_revisions t WHERE rider_id IS DISTINCT FROM :r"), {"r": except_rider}))
    return rows


def everything_as_text(db) -> str:
    with db.bind.connect() as conn:
        tables = [r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))]
        return "\n".join(r[0] for t in tables for r in conn.execute(text(f'SELECT t::text FROM "{t}" t')))


class PauseRun:
    """Holds the worker between solving and committing for the matching runs only."""

    def __init__(self, service, match=lambda run_id: True, hook="after_solve"):
        self.reached, self.go, self.match = threading.Event(), threading.Event(), match
        service.hooks[hook] = self

    def __call__(self, run_id):
        if self.match(run_id):
            self.reached.set()
            assert self.go.wait(60)

    def wait(self):
        assert self.reached.wait(60), "worker never reached the hook"


def rider_runs(db):
    db.expire_all()
    return {r.id: r for r in db.scalars(select(PlanningRun).where(PlanningRun.scope == "rider")).all()}


def two_workers(app):
    """A second worker thread, so a round run can commit while a rider run is held."""
    svc = app.state.planning
    svc.limits = replace(svc.limits, workers=2)


# ------------------------------------------------------------------ only the rider's own remainder (A18)


def test_reroute_from_the_current_position_changes_only_the_riders_own_sequence(world, db, caplog):
    w = world
    planned(w)
    a = codes_of(w, "Rider A")
    assert len(a) >= 4
    update(w, "Rider A", a[0], "Postponed")
    update(w, "Rider A", a[1], "Completed")
    before = frozen_rows(db, except_rider=uuid.UUID(w.ids["Rider A"]))
    views_before = {n: deliveries(w.browsers[n], w.rid).json() for n in ("Rider B", "Rider C")}
    caplog.set_level(logging.DEBUG)

    run = reroute_now(w, "Rider A", gps())
    assert run["origin_kind"] == "current_position" and run["revision"] == 1
    assert frozen_rows(db, except_rider=uuid.UUID(w.ids["Rider A"])) == before  # nothing else written
    for n, v in views_before.items():  # other riders: same route, sequence, plan and validity
        now = deliveries(w.browsers[n], w.rid).json()
        assert (now["sequence"], now["plan"]["route"], now["plan"]["rider_route"]) == \
            (v["sequence"], v["plan"]["route"], v["plan"]["rider_route"])

    view = deliveries(w.browsers["Rider A"], w.rid).json()
    rr = view["plan"]["rider_route"]
    assert rr["revision"]["number"] == 1 and rr["revision"]["origin_kind"] == "current_position"
    assert rr["revision"]["trigger"] == "rider_request" and rr["origin_label"].startswith("your current position")
    assert sorted(seq_codes(view)) == sorted(a[2:])  # only the remaining Pending orders
    assert [o["order_code"] for o in view["postponed"]] == [a[0]] and [o["order_code"] for o in view["completed"]] == [a[1]]
    assert view["plan"]["out_of_date"] is False and rr["awaiting_recalculation"] is None
    # Distance from the device position along the new order to Home, on the recorded real roads.
    path = ["gps_r1"] + [w.codes[c] for c in seq_codes(view)] + ["home_r1"]
    assert (rr["road_distance_m"], rr["road_duration_s"]) == recorded_cost("motor_scooter", path)

    admin_view = w.admin.get(f"/api/admin/rounds/{w.rid}/plan")
    ra = routes(admin_view.json())["Rider A"]["rider_route"]
    assert ra["revision"]["origin_kind"] == "current_position"
    assert [o["order_code"] for s in ra["stops"] for o in s["orders"]] == seq_codes(view)
    assert admin_view.json()["unplanned_pending"] == []
    # The device position is used in memory only: never stored, logged or returned.
    dump = everything_as_text(db) + admin_view.text + json.dumps(view) + caplog.text
    for s in GPS_STRINGS:
        assert s not in dump


def test_reroute_is_refused_up_front_with_coded_reasons_and_writes_nothing(world, db):
    w = world
    assert code(ask(w, "Rider A", gps(), plan_version=1, revision=0)) == "NO_PLAN"
    planned(w)
    a = codes_of(w, "Rider A")
    assert code(ask(w, "Rider A", gps(), plan_version=9)) == "ROUTE_CHANGED"
    assert code(ask(w, "Rider A", gps(), revision=3)) == "ROUTE_CHANGED"
    for c in a:
        update(w, "Rider A", c, "Completed")
    assert code(ask(w, "Rider A", gps())) == "NOTHING_TO_REROUTE"
    # A genuine admin change makes the whole round out of date: only the admin can replan.
    o = orders_by_code(w)["RW-P004"]
    assert w.admin.send("POST", f"/api/admin/orders/{o['id']}/pin", json={"version": o["version"], **{
        "lat": PUBLIC_DU["ramjas"]["lat"], "lng": PUBLIC_DU["ramjas"]["lng"]}}).status_code == 200
    r = ask(w, "Rider B", gps())
    assert r.status_code == 409 and code(r) == "ROUND_OUT_OF_DATE"
    assert deliveries(w.browsers["Rider B"], w.rid).json()["reroute"]["blocked"]["code"] == "ROUND_OUT_OF_DATE"
    assert rider_runs(db) == {}
    # Another rider's round, or a round that does not exist: the same 404.
    other = w.browsers["Rider A"].send("POST", f"/api/rider/rounds/{uuid.uuid4()}/reroute",
                                       json={"origin": gps(), "expected_plan_version": 1, "expected_revision": 0})
    assert other.status_code == 404


# ------------------------------------------------------------------ origins (A19)


def test_origins_are_explicit_labelled_and_never_substituted(world, db, clock):
    w = world
    planned(w)
    a = codes_of(w, "Rider A")
    b = w.browsers["Rider A"]
    opts = deliveries(b, w.rid).json()["reroute"]
    assert opts["available"] and opts["last_completed_stop"] is None and opts["configured_start_allowed"]
    assert code(ask(w, "Rider A", {"kind": "last_completed_stop", "order_id": str(uuid.uuid4())})) == "NO_COMPLETED_STOP"

    # No completed stop yet: the configured start, chosen explicitly, is the honest fallback.
    run = reroute_now(w, "Rider A", {"kind": "configured_start"})
    view = deliveries(b, w.rid).json()
    rr = view["plan"]["rider_route"]
    assert rr["revision"]["origin_kind"] == "configured_start" and "not your current position" in rr["origin_label"]
    path = ["office"] + [w.codes[c] for c in seq_codes(view)] + ["home_r1"]
    assert rr["road_distance_m"] == recorded_cost("motor_scooter", path)[0]
    assert run["revision"] == 1

    # A completion recorded by the rider: when and by whom.
    clock.advance(minutes=3)
    first = seq_codes(view)[0]
    update(w, "Rider A", first, "Completed")
    db.expire_all()
    done = db.scalar(select(Order).where(Order.order_code == first))
    a_user = db.scalar(select(User.id).where(User.username == "rider_a"))
    assert (done.completed_at, done.completed_by) == (clock(), a_user)
    opts = deliveries(b, w.rid).json()["reroute"]
    assert opts["last_completed_stop"]["order_code"] == first and not opts["configured_start_allowed"]
    assert "not your current position" in opts["last_completed_stop"]["label"]
    assert code(ask(w, "Rider A", {"kind": "configured_start"})) == "COMPLETED_STOP_AVAILABLE"

    clock.advance(minutes=3)
    second = seq_codes(deliveries(b, w.rid).json())[0]
    update(w, "Rider A", second, "Completed")
    stale_choice = ask(w, "Rider A", {"kind": "last_completed_stop", "order_id": str(done.id)})
    assert stale_choice.status_code == 409 and code(stale_choice) == "ORIGIN_CHANGED"
    b_order = orders_by_code(w)[codes_of(w, "Rider B")[0]]  # another rider's order is never usable
    assert code(ask(w, "Rider A", {"kind": "last_completed_stop", "order_id": b_order["id"]})) == "ORIGIN_CHANGED"
    last_id = orders_by_code(w)[second]["id"]
    run = reroute_now(w, "Rider A", {"kind": "last_completed_stop", "order_id": last_id})
    view = deliveries(b, w.rid).json()
    rev = view["plan"]["rider_route"]["revision"]
    assert (run["revision"], rev["origin_kind"], rev["origin_order_code"]) == (2, "last_completed_stop", second)
    path = [w.codes[second]] + [w.codes[c] for c in seq_codes(view)] + ["home_r1"]
    assert view["plan"]["rider_route"]["road_distance_m"] == recorded_cost("motor_scooter", path)[0]
    db.expire_all()
    revs = db.scalars(select(RouteRevision).where(RouteRevision.rider_id == uuid.UUID(w.ids["Rider A"]))
                      .order_by(RouteRevision.revision)).all()
    assert [(r.revision, r.is_current, r.superseded_at is not None) for r in revs] == [(1, False, True), (2, True, False)]

    # Completions without a recorded time (before 4B) are never offered: nothing is invented.
    with db.bind.begin() as conn:
        conn.execute(text("UPDATE orders SET completed_at = NULL, completed_by = NULL"))
    opts = deliveries(b, w.rid).json()["reroute"]
    assert opts["last_completed_stop"] is None and opts["configured_start_allowed"]
    # An admin's completion is not the rider's location either; reopening clears the record.
    rest = seq_codes(deliveries(b, w.rid).json())[0]
    o = orders_by_code(w)[rest]
    assert w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": "Completed"}).status_code == 200
    assert deliveries(b, w.rid).json()["reroute"]["last_completed_stop"] is None
    o = orders_by_code(w)[rest]
    assert w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": "Pending"}).status_code == 200
    db.expire_all()
    reopened = db.scalar(select(Order).where(Order.order_code == rest))
    assert (reopened.completed_at, reopened.completed_by) == (None, None)
    assert len(a) >= 4


@pytest.mark.parametrize("origin, expected", [
    (gps(accuracy_m=101), "POSITION_UNUSABLE"),
    (gps(age_s=61), "POSITION_UNUSABLE"),
    (gps(lat=28.40), "POSITION_UNUSABLE"),           # outside the service area the local tiles cover
    (gps(accuracy_m=None), "POSITION_UNUSABLE"),
    ({"kind": "configured_start", "lat": GPS["lat"], "lng": GPS["lng"]}, "ORIGIN_INVALID"),
    ({"kind": "current_position", "lat": GPS["lat"], "lng": GPS["lng"], "accuracy_m": 10, "age_s": 1,
      "order_id": str(uuid.uuid4())}, "ORIGIN_INVALID"),
], ids=["inaccurate", "old", "outside", "incomplete", "coords-on-start", "order-on-position"])
def test_device_positions_are_checked_and_refusals_do_not_echo_them(world, db, origin, expected):
    w = world
    planned(w)
    r = ask(w, "Rider A", origin)
    assert r.status_code == 422 and code(r) == expected, r.text
    for s in GPS_STRINGS:
        assert s not in r.text
    assert rider_runs(db) == {}


def test_a_non_finite_position_is_refused(world, db):
    w = world
    planned(w)
    body = ('{"origin": {"kind": "current_position", "lat": NaN, "lng": 77.2, "accuracy_m": 5, "age_s": 1},'
            ' "expected_plan_version": 1, "expected_revision": 0}')
    r = w.browsers["Rider A"].send("POST", f"/api/rider/rounds/{w.rid}/reroute", content=body,
                                   headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and rider_runs(db) == {}


def test_the_position_limits_are_configurable_local_defaults(monkeypatch):
    s = load_settings()
    assert (s.reroute.gps_max_accuracy_m, s.reroute.gps_max_age_s) == (100.0, 60.0)
    monkeypatch.setenv("ROUTEWISE_REROUTE_GPS_MAX_ACCURACY_M", "50")
    monkeypatch.setenv("ROUTEWISE_REROUTE_GPS_MAX_AGE_S", "30")
    s = load_settings()
    assert (s.reroute.gps_max_accuracy_m, s.reroute.gps_max_age_s) == (50.0, 30.0)


# ------------------------------------------------------------------ destination change (A20, R23)


def test_destination_change_recalculates_only_that_rider_after_confirmation(world, db):
    w = world
    planned(w)
    a = codes_of(w, "Rider A")
    update(w, "Rider A", a[0], "Completed")
    b = w.browsers["Rider A"]
    assert choose(b, w.rid, "warehouse").status_code == 200
    view = deliveries(b, w.rid).json()
    assert view["plan"]["rider_route"]["awaiting_recalculation"] == "destination_changed"
    assert code(ask(w, "Rider A", gps())) == "NOT_CONFIRMED"
    for n in ("Rider B", "Rider C"):  # nobody else is out of date or asked to reconfirm
        v = deliveries(w.browsers[n], w.rid).json()
        assert v["plan"]["out_of_date"] is False and v["plan"]["rider_route"]["awaiting_recalculation"] is None
        assert v["setup"]["confirmation"] == "confirmed"
    assert confirm(b, w.rid).status_code == 200
    before = frozen_rows(db, except_rider=uuid.UUID(w.ids["Rider A"]))

    reroute_now(w, "Rider A", gps())
    assert frozen_rows(db, except_rider=uuid.UUID(w.ids["Rider A"])) == before
    view = deliveries(b, w.rid).json()
    rr = view["plan"]["rider_route"]
    assert rr["revision"]["trigger"] == "endpoint_change" and rr["destination"]["kind"] == "warehouse"
    assert rr["awaiting_recalculation"] is None and view["plan"]["out_of_date"] is False
    assert [o["order_code"] for o in view["completed"]] == [a[0]] and sorted(seq_codes(view)) == sorted(a[1:])
    path = ["gps_r1"] + [w.codes[c] for c in seq_codes(view)] + ["warehouse"]
    assert rr["road_distance_m"] == recorded_cost("motor_scooter", path)[0]
    assert view["plan"]["route"]["destination"]["kind"] == "home"  # the admin plan itself is unchanged

    # The admin replans the whole round later: the new plan supersedes the rider's revision.
    v2 = plan_now(w)
    assert v2["summary"]["rider_revisions_superseded"] == ["Rider A"]
    db.expire_all()
    old = db.scalar(select(RouteRevision).where(RouteRevision.rider_id == uuid.UUID(w.ids["Rider A"])))
    assert old.is_current is False and old.superseded_at is not None
    view = deliveries(b, w.rid).json()
    assert view["plan"]["version"] == 2 and view["plan"]["rider_route"]["revision"] is None
    assert seq_codes(view) == [o["order_code"] for s in routes(v2)["Rider A"]["stops"] for o in s["orders"]]


# ------------------------------------------------------------------ reinsertion, priority, open routes, profiles


def test_a_returned_postponed_order_is_reinserted_only_by_an_explicit_reroute(world):
    w = world
    planned(w)
    a = codes_of(w, "Rider A")
    update(w, "Rider A", a[0], "Postponed")
    reroute_now(w, "Rider A", gps())
    b = w.browsers["Rider A"]
    assert a[0] not in seq_codes(deliveries(b, w.rid).json())
    view = update(w, "Rider A", a[0], "Pending")["view"]  # explicit return (D08): not in this revision
    assert [o["order_code"] for o in view["unsequenced"]] == [a[0]] and a[0] not in seq_codes(view)
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()["unplanned_pending"] == [a[0]]
    reroute_now(w, "Rider A", gps())
    view = deliveries(b, w.rid).json()
    assert sorted(seq_codes(view)) == sorted(a) and view["unsequenced"] == []
    assert view["plan"]["rider_route"]["revision"]["number"] == 2
    assert w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()["unplanned_pending"] == []


def test_priority_stays_first_and_a_last_stop_route_stays_open(world):
    w = world
    assert lock(w, "RW-P009", "Rider C").status_code == 200
    assert priority(w, "RW-P009").status_code == 200
    plan_now(w)
    c = codes_of(w, "Rider C")
    assert c[0] == "RW-P009"
    update(w, "Rider C", c[1], "Completed")
    reroute_now(w, "Rider C", gps())
    view = deliveries(w.browsers["Rider C"], w.rid).json()
    rr = view["plan"]["rider_route"]
    assert seq_codes(view)[0] == "RW-P009"  # the remaining first-priority order is still first
    assert rr["open_route"] is True and rr["destination"]["kind"] == "last_stop"
    path = ["gps_r1"] + [w.codes[x] for x in seq_codes(view)]  # ends at the last delivery
    assert (rr["road_distance_m"], rr["road_duration_s"]) == recorded_cost("motor_scooter", path)


def test_each_rider_is_rerouted_with_their_own_vehicle_profile(world, db):
    w = world
    planned(w)
    w.provider.calls.clear()
    reroute_now(w, "Rider B", gps())  # bike
    reroute_now(w, "Rider A", gps())  # scooter
    assert [p for p, _ in w.provider.calls] == ["motorcycle", "motor_scooter"]
    db.expire_all()
    profiles = {str(r.rider_id): (r.vehicle, r.profile) for r in db.scalars(select(RouteRevision)).all()}
    assert profiles == {w.ids["Rider B"]: ("bike", "motorcycle"), w.ids["Rider A"]: ("scooter", "motor_scooter")}
    view = deliveries(w.browsers["Rider B"], w.rid).json()
    path = ["gps_r1"] + [w.codes[x] for x in seq_codes(view)] + ["custom_r2"]
    assert view["plan"]["rider_route"]["road_distance_m"] == recorded_cost("motorcycle", path)[0]


def test_failures_keep_the_last_valid_route(world, db):
    w = world
    planned(w)
    before = deliveries(w.browsers["Rider A"], w.rid).json()
    w.provider.fail = True
    run = reroute_now(w, "Rider A", gps(), expect="failed")
    assert run["error"]["code"] == "ROUTING_ENGINE_UNAVAILABLE"
    w.provider.fail = False
    w.provider.missing = {("gps_r1", fid, None) for fid in PUBLIC_DU}  # no road out of the position
    run = reroute_now(w, "Rider A", gps(), expect="failed")
    assert run["error"]["code"] == "UNROUTABLE_ORIGIN"
    after = deliveries(w.browsers["Rider A"], w.rid).json()
    assert (after["sequence"], after["plan"]["rider_route"]) == (before["sequence"], before["plan"]["rider_route"])
    db.expire_all()
    assert db.scalar(select(RouteRevision)) is None


# ------------------------------------------------------------------ bounded work, isolation of runs


def test_one_reroute_at_a_time_per_rider_and_runs_are_private(world, db, app):
    w = world
    planned(w)
    pause = PauseRun(app.state.planning)
    first = ask(w, "Rider A", gps())
    assert first.status_code == 202
    pause.wait()
    again = ask(w, "Rider A", gps())
    assert again.status_code == 409 and code(again) == "REROUTE_IN_PROGRESS"
    assert again.json()["detail"]["details"] == [first.json()["id"]]
    assert deliveries(w.browsers["Rider A"], w.rid).json()["reroute"]["in_progress_run_id"] == first.json()["id"]
    assert w.browsers["Rider B"].get(f"/api/rider/reroutes/{first.json()['id']}").status_code == 404
    assert w.browsers["Rider A"].get(f"/api/rider/reroutes/{uuid.uuid4()}").status_code == 404
    pause.go.set()
    assert wait_reroute(w, "Rider A", first.json()["id"])["state"] == "succeeded"
    assert [r.state for r in rider_runs(db).values()] == ["succeeded"]
    # Admin run lists show the admin's own runs only.
    assert all(r["state"] == "succeeded" for r in w.admin.get(f"/api/admin/rounds/{w.rid}/planning-runs").json())
    assert len(w.admin.get(f"/api/admin/rounds/{w.rid}/planning-runs").json()) == 1


def test_an_interrupted_rider_run_never_saves_a_revision(world, db, app, clock):
    w = world
    planned(w)
    pause = PauseRun(app.state.planning)
    run_id = ask(w, "Rider A", gps()).json()["id"]
    pause.wait()
    assert recover_interrupted_runs(app.state.session_factory, clock()) == 1  # as after an API restart
    pause.go.set()
    assert wait_reroute(w, "Rider A", run_id)["state"] == "interrupted"
    db.expire_all()
    assert db.scalar(select(RouteRevision)) is None


# ------------------------------------------------------------------ races during the solve


def _own_status(w):
    a = seq_codes(deliveries(w.browsers["Rider A"], w.rid).json())
    return post_status(w.browsers["Rider A"], orders_by_code(w)[a[-1]]["id"], "Completed",
                       orders_by_code(w)[a[-1]]["version"])


def _own_postpone(w):
    """Status only (no completion record changes with it)."""
    a = seq_codes(deliveries(w.browsers["Rider A"], w.rid).json())
    return post_status(w.browsers["Rider A"], orders_by_code(w)[a[-1]]["id"], "Postponed",
                       orders_by_code(w)[a[-1]]["version"])


def _own_destination(w):
    return choose(w.browsers["Rider A"], w.rid, "warehouse")


def _admin_pin(w):
    o = orders_by_code(w)[codes_of(w, "Rider A")[-1]]
    return w.admin.send("POST", f"/api/admin/orders/{o['id']}/pin", json={"version": o["version"], **{
        "lat": PUBLIC_DU["ramjas"]["lat"], "lng": PUBLIC_DU["ramjas"]["lng"]}})


def _admin_status(w):
    o = orders_by_code(w)[codes_of(w, "Rider A")[-1]]
    return w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": "Postponed"})


def _capacity(w):
    v = setup_of(w.browsers["Rider A"], w.rid).json()["config_version"]
    return put_rider(w.admin, w.rid, w.ids["Rider A"], version=v, capacity=6)


def _ownership(w):
    """The admin moves one of A's Pending orders to another rider (an ownership change)."""
    return lock(w, codes_of(w, "Rider A")[-1], "Rider B")


def _deactivate(w):
    user_id = w.db.scalar(select(User.id).where(User.username == "rider_a"))
    with w.app.state.session_factory() as s:
        accounts.deactivate_user(s, user_id, w.app.state.clock())

    class Ok:
        status_code = 200
    return Ok()


@pytest.mark.parametrize("change", [_own_status, _own_postpone, _own_destination, _admin_pin, _admin_status, _capacity, _ownership,
                                    _deactivate], ids=lambda f: f.__name__.strip("_"))
def test_a_change_to_the_riders_own_input_during_the_solve_makes_the_reroute_stale(world, db, app, change):
    w = world
    planned(w)
    before = deliveries(w.browsers["Rider A"], w.rid).json()
    pause = PauseRun(app.state.planning)
    r = ask(w, "Rider A", gps())
    assert r.status_code == 202
    pause.wait()
    assert change(w).status_code == 200
    pause.go.set()
    db.expire_all()
    run = db.get(PlanningRun, uuid.UUID(r.json()["id"]))
    for _ in range(600):
        db.expire_all()
        run = db.get(PlanningRun, uuid.UUID(r.json()["id"]))
        if run.state in TERMINAL:
            break
        time.sleep(0.05)
    assert run.state == "stale" and run.error_code == "INPUTS_CHANGED", (run.state, run.error_code)
    assert db.scalar(select(RouteRevision)) is None
    if change is not _deactivate:
        view = deliveries(w.browsers["Rider A"], w.rid).json()
        assert view["plan"]["rider_route"]["revision"] is None and view["plan"]["version"] == before["plan"]["version"]


def test_other_riders_progress_and_reroutes_never_make_this_reroute_stale(world, db, app):
    w = world
    planned(w)
    two_workers(app)
    a_run = {}
    pause = PauseRun(app.state.planning, match=lambda run_id: str(run_id) == a_run.get("id"))
    r = ask(w, "Rider A", gps())
    a_run["id"] = r.json()["id"]
    pause.wait()
    b = codes_of(w, "Rider B")
    update(w, "Rider B", b[0], "Completed")         # another rider's progress (bumps input_version)
    update(w, "Rider B", b[1], "Postponed")
    reroute_now(w, "Rider C", gps())                 # another rider's own reroute commits meanwhile
    pause.go.set()
    assert wait_reroute(w, "Rider A", a_run["id"])["state"] == "succeeded"
    db.expire_all()
    current = {str(rv.rider_id) for rv in db.scalars(select(RouteRevision).where(RouteRevision.is_current.is_(True))).all()}
    assert current == {w.ids["Rider A"], w.ids["Rider C"]}


def test_admin_replanning_wins_over_a_reroute_in_flight(world, db, app):
    w = world
    planned(w)
    two_workers(app)
    a_run = {}
    pause = PauseRun(app.state.planning, match=lambda run_id: str(run_id) == a_run.get("id"))
    r = ask(w, "Rider A", gps())
    a_run["id"] = r.json()["id"]
    pause.wait()
    v2 = plan_now(w)  # the admin's round plan commits while the reroute is held
    pause.go.set()
    run = wait_reroute(w, "Rider A", a_run["id"])
    assert run["state"] == "stale" and run["error"]["code"] == "ROUND_REPLANNED"
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    assert view["plan"]["version"] == v2["version"] == 2 and view["plan"]["rider_route"]["revision"] is None
    db.expire_all()
    assert db.scalar(select(RouteRevision)) is None


def test_a_new_reroute_is_refused_while_the_admin_is_replanning(world, db, app):
    w = world
    planned(w)
    pause = PauseRun(app.state.planning)
    run_id = w.admin.send("POST", f"/api/admin/rounds/{w.rid}/optimize").json()["id"]
    pause.wait()
    r = ask(w, "Rider A", gps())
    assert r.status_code == 409 and code(r) == "ROUND_REPLANNING"
    assert deliveries(w.browsers["Rider A"], w.rid).json()["reroute"]["blocked"]["code"] == "ROUND_REPLANNING"
    pause.go.set()
    assert wait_run(w, run_id)["state"] == "succeeded"
    assert rider_runs(db) == {}


# ------------------------------------------------------------------ the final commit point


def _other_status(w):
    c = codes_of(w, "Rider C")
    o = item(deliveries(w.browsers["Rider C"], w.rid).json(), c[0])
    return post_status(w.browsers["Rider C"], o["id"], "Completed", o["version"])


@pytest.mark.parametrize("edit", [_own_status, _other_status, _admin_pin], ids=["own-status", "other-status", "admin-pin"])
def test_an_edit_racing_the_reroute_commit_after_its_final_check_lands_after_it(world, db, db_url, app, edit):
    """The commit has passed its final check and holds the round lock. Any edit that needs the
    round waits and lands after the revision; the outcome is serial, never interleaved."""
    w = world
    planned(w)
    gate = PauseRun(app.state.planning, hook="before_write")
    r = ask(w, "Rider A", gps())
    gate.wait()
    result = {}
    editor = threading.Thread(target=lambda: result.setdefault("response", edit(w)))
    editor.start()
    engine = create_engine(db_url)
    try:
        edit_first = _edit_committed_or_blocked(engine, editor)
    finally:
        gate.go.set()
        engine.dispose()
    editor.join(30)
    assert not edit_first and result["response"].status_code == 200, result
    assert wait_reroute(w, "Rider A", r.json()["id"])["state"] == "succeeded"
    db.expire_all()
    assert db.scalar(select(RouteRevision).where(RouteRevision.is_current.is_(True))) is not None
    plan = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    assert plan["out_of_date"] is (edit is _admin_pin)  # a rider's progress never invalidates routes
