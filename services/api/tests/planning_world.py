"""Shared fixtures for Phase 2B planning tests.

Orders are SYNTHETIC customers placed on public OpenStreetMap points around DU North Campus;
Office/Warehouse/Home/Custom are synthetic roles on public stations. Road costs come from the
recorded real local-Valhalla matrices (tests/recorded_matrix.py)."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from routewise_api.models import DeliveryRound, Order, Rider, User

from .conftest import Browser, make_user
from .recorded_matrix import PUBLIC_DU, RECORDINGS, RecordedDUProvider
from .test_round_setup import choose, confirm, put_rider, set_depot

ORDER_POINTS = ["kirori_mal", "hansraj", "hindu_college", "st_stephens", "miranda_house", "ramjas", "srcc",
                "daulat_ram", "kamla_nagar", "gtb_nagar", "civil_lines"]
TERMINAL = {"succeeded", "failed", "stale", "interrupted"}


class PlanWorld:
    pass


def add_orders(db, round_id, points, start=1):
    codes = {}
    for i, place in enumerate(points, start=start):
        code = f"RW-P{i:03d}"
        db.add(Order(order_code=code, round_id=round_id, source_row=i + 1, customer_name=f"Test Customer P{i}",
                     product="Synthetic parcel", contact=f"0000000{i:04d}", location_link="geo:0,0",
                     location_state="resolved", lat=PUBLIC_DU[place]["lat"], lng=PUBLIC_DU[place]["lng"],
                     location_source="geo_uri"))
        codes[code] = place
    db.commit()
    return codes


def make_world(app, admin, db, *, points=ORDER_POINTS, riders=None, provider=None, live=False) -> PlanWorld:
    """riders: list of (username, display, vehicle, capacity, start, destination kind, destination point)."""
    w = PlanWorld()
    w.app, w.admin, w.db = app, admin, db
    w.provider = None if live else (provider or RecordedDUProvider())
    app.state.planning.provider_override = w.provider  # None: the real local Valhalla tiles
    riders = riders or [
        ("rider_a", "Rider A", "scooter", 5, "office", "home", "home_r1"),
        ("rider_b", "Rider B", "bike", 5, "warehouse", "custom", "custom_r2"),
        ("rider_c", "Rider C", "scooter", 4, "warehouse", "last_stop", None),
    ]
    owner = db.scalar(select(User).where(User.username == "admin1"))
    rnd = DeliveryRound(name="Synthetic planning round", created_by=owner.id)
    db.add(rnd)
    db.flush()
    w.rid = str(rnd.id)
    w.codes = add_orders(db, rnd.id, points)
    assert set_depot(admin, "office", PUBLIC_DU["office"]).status_code == 200
    assert set_depot(admin, "warehouse", PUBLIC_DU["warehouse"]).status_code == 200
    w.ids, w.browsers, w.spec = {}, {}, {}
    for username, display, vehicle, capacity, start, kind, point in riders:
        u = make_user(app, username, "rider", rider_name=display, vehicle=vehicle)
        rider_id = str(db.scalar(select(Rider.id).where(Rider.user_id == u.id)))
        w.ids[display] = rider_id
        w.spec[display] = (vehicle, capacity, start, kind, point)
        b = Browser(app)
        assert b.login(username).status_code == 200
        w.browsers[display] = b
        assert put_rider(admin, w.rid, rider_id, capacity=capacity, start=start, vehicle=vehicle).status_code == 200
        assert choose(b, w.rid, kind, PUBLIC_DU[point] if point else None).status_code == 200
        assert confirm(b, w.rid).status_code == 200
    return w


@pytest.fixture
def world(app, admin, db):
    return make_world(app, admin, db)


def optimize(w: PlanWorld):
    return w.admin.send("POST", f"/api/admin/rounds/{w.rid}/optimize")


def wait_run(w: PlanWorld, run_id: str, timeout: float = 60.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        run = w.admin.get(f"/api/admin/planning-runs/{run_id}").json()
        if run["state"] in TERMINAL:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def plan_now(w: PlanWorld) -> dict:
    r = optimize(w)
    assert r.status_code == 202, r.text
    run = wait_run(w, r.json()["id"])
    assert run["state"] == "succeeded", run
    return w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()


def orders_by_code(w: PlanWorld) -> dict:
    return {o["order_code"]: o for o in w.admin.get(f"/api/admin/rounds/{w.rid}/orders").json()}


def route_points(w: PlanWorld, route: dict) -> list[str]:
    """Fixture ids along a route: start depot, each stop, then the fixed destination if any."""
    name = route["rider"]
    vehicle, capacity, start, kind, point = w.spec[name]
    path = [start] + [w.codes[s["orders"][0]["order_code"]] for s in route["stops"]]
    if kind in ("office", "warehouse"):
        path.append(kind)
    elif kind in ("home", "custom"):
        path.append(point)
    return path


def recorded_cost(profile: str, path: list[str]) -> tuple[int, int]:
    elements = RECORDINGS[profile][1]
    dist = dur = 0
    for a, b in zip(path, path[1:]):
        if a == b:
            continue
        e = elements[(a, b)]
        assert e.distance_m is not None, (a, b)
        dist += e.distance_m
        dur += e.duration_s
    return dist, dur
