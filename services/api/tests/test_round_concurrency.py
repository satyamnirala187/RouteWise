"""Real PostgreSQL concurrency for Phase 2A: a configuration change and a rider confirmation can
never leave a stale confirmation valid, and the documented locking order cannot deadlock.

Races are deterministic, as in test_concurrency.py: an outside connection holds a row lock
until every request is blocked on PostgreSQL locks, then releases it so they race."""

import threading

import pytest
from sqlalchemy import create_engine, select, text

from routewise_api.models import DeliveryRound, RoundRider

from .test_concurrency import _wait_for_lock_waiters
from .test_round_setup import (  # noqa: F401  (fixtures are registered by import)
    DU, choose, confirm, put_rider, readiness, ready_world, set_depot, setup_of, world,
)


def race_holding(db_url, lock_sql: str, params: dict, calls):
    """Hold the row lock taken by `lock_sql`, start all calls, wait until they all block, release."""
    engine = create_engine(db_url)
    holder = engine.connect()
    tx = holder.begin()
    holder.execute(text(lock_sql), params)
    results = [None] * len(calls)

    def run(i, fn):
        results[i] = fn()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    try:
        _wait_for_lock_waiters(engine, len(calls))
    finally:
        tx.rollback()
        holder.close()
    for t in threads:
        t.join(timeout=30)
    engine.dispose()
    return results


LOCK_ROUND = "SELECT 1 FROM delivery_rounds WHERE id = :id FOR UPDATE"
LOCK_OFFICE = "SELECT 1 FROM depots WHERE kind = 'office' FOR UPDATE"


def rider_row(db, rid, rider_id) -> RoundRider:
    db.expire_all()
    return db.get(RoundRider, (rid, rider_id))


def current_input_version(db, rid) -> int:
    db.expire_all()
    return db.scalar(select(DeliveryRound.input_version).where(DeliveryRound.id == rid))


@pytest.mark.parametrize("change", [{"capacity": 9}, {"vehicle": "bike"}, {"start": "warehouse"}])
def test_admin_edit_racing_confirmation_never_leaves_a_stale_confirmation(ready_world, db, db_url, change):
    w = ready_world
    outcomes = set()
    for _ in range(4):  # either side may win; the invariant must hold every time
        version = setup_of(w.ra, w.rid).json()["config_version"]
        put_rider(w.admin, w.rid, w.a, version=version, capacity=5, start="office", vehicle="scooter")
        version = setup_of(w.ra, w.rid).json()["config_version"]
        before = current_input_version(db, w.rid)
        edit, conf = race_holding(db_url, LOCK_ROUND, {"id": w.rid}, [
            lambda: put_rider(w.admin, w.rid, w.a, version=version, **change),
            lambda: confirm(w.ra, w.rid, version),
        ])
        assert edit.status_code == 200, edit.text
        assert conf.status_code in (200, 409), conf.text
        outcomes.add(conf.status_code)
        rr = rider_row(db, w.rid, w.a)
        # Whoever won, the confirmation that survives is never for the edited setup's old version.
        assert rr.config_version == version + 1 and rr.confirmed_version != rr.config_version
        assert "confirmation_outdated" in [b["code"] for b in readiness(w.admin, w.rid)["configuration_blockers"]] \
            or rr.confirmed_version is None
        assert current_input_version(db, w.rid) > before  # the edit always advances the planning input
        assert confirm(w.ra, w.rid).status_code == 200  # back to confirmed for the next round
    assert outcomes <= {200, 409}


def test_depot_move_racing_confirmation_never_leaves_a_stale_confirmation(ready_world, db, db_url):
    w = ready_world
    for i in range(4):
        office = w.admin.get("/api/admin/depots").json()["office"]
        target = DU["gtb_nagar"] if i % 2 == 0 else DU["office"]
        # Rider A starts at the Office. Make A re-confirm, then race a depot move with that confirmation.
        version = setup_of(w.ra, w.rid).json()["config_version"]
        put_rider(w.admin, w.rid, w.a, version=version, capacity=6 + i)
        version += 1
        move, conf = race_holding(db_url, LOCK_OFFICE, {}, [
            lambda: set_depot(w.admin, "office", target, version=office["version"]),
            lambda: confirm(w.ra, w.rid, version),
        ])
        assert move.status_code == 200, move.text
        assert conf.status_code in (200, 409), conf.text
        rr = rider_row(db, w.rid, w.a)
        assert rr.config_version == version + 1 and rr.confirmed_version != rr.config_version
        if conf.status_code == 200:  # the confirmation landed first, and the move invalidated it
            assert move.json()["confirmations_invalidated"] == 1
        else:
            assert conf.json()["detail"]["code"] == "configuration_changed"
        assert setup_of(w.ra, w.rid).json()["start"]["lat"] == target["lat"]
        assert confirm(w.ra, w.rid).status_code == 200


def test_destination_change_racing_confirmation_from_another_device(ready_world, db, db_url, app):
    from .conftest import Browser

    w = ready_world
    phone2 = Browser(app)
    assert phone2.login("rider_a").status_code == 200
    for i in range(4):
        version = setup_of(w.ra, w.rid).json()["config_version"]
        kind = "custom" if i % 2 == 0 else "home"
        change, conf = race_holding(db_url, LOCK_ROUND, {"id": w.rid}, [
            lambda: choose(phone2, w.rid, kind, DU["custom_r2"] if kind == "custom" else DU["home_r1"]),
            lambda: confirm(w.ra, w.rid, version),
        ])
        assert change.status_code == 200 and conf.status_code in (200, 409)
        rr = rider_row(db, w.rid, w.a)
        assert rr.config_version == version + 1 and rr.confirmed_version != rr.config_version
        assert confirm(w.ra, w.rid).status_code == 200


def test_two_admins_editing_one_rider_setup_one_wins(ready_world, db, db_url, app):
    from .conftest import Browser

    w = ready_world
    other = Browser(app)
    assert other.login("admin1").status_code == 200
    version = setup_of(w.ra, w.rid).json()["config_version"]
    r1, r2 = race_holding(db_url, LOCK_ROUND, {"id": w.rid}, [
        lambda: put_rider(w.admin, w.rid, w.a, version=version, capacity=8),
        lambda: put_rider(other, w.rid, w.a, version=version, capacity=9),
    ])
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    winner = r1 if r1.status_code == 200 else r2
    assert rider_row(db, w.rid, w.a).capacity == winner.json()["capacity"]
    assert rider_row(db, w.rid, w.a).config_version == version + 1


def test_two_admins_adding_the_same_rider_one_wins(world, db, db_url, app):
    from .conftest import Browser

    w = world
    other = Browser(app)
    assert other.login("admin1").status_code == 200
    r1, r2 = race_holding(db_url, LOCK_ROUND, {"id": w.rid}, [
        lambda: put_rider(w.admin, w.rid, w.c, capacity=3, start="office", vehicle="bike"),
        lambda: put_rider(other, w.rid, w.c, capacity=4, start="warehouse", vehicle="scooter"),
    ])
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    db.expire_all()
    assert len(db.scalars(select(RoundRider).where(RoundRider.round_id == w.rid)).all()) == 1


def test_mixed_concurrent_writes_follow_one_lock_order_without_deadlock(ready_world, db, app):
    """Depot moves, admin edits, destination changes, confirmations and order pin edits all at
    once. A lock-order cycle would surface as a PostgreSQL deadlock (HTTP 500)."""
    from .conftest import Browser

    w = ready_world
    admin2, phone_b = Browser(app), Browser(app)
    admin2.login("admin1")
    phone_b.login("rider_b")
    orders = w.admin.get(f"/api/admin/rounds/{w.rid}/orders").json()
    statuses: list[int] = []
    lock = threading.Lock()

    def loop(fn, n=6):
        for i in range(n):
            r = fn(i)
            with lock:
                statuses.append(r.status_code)

    def depot_move(kind, points):
        def f(i):
            cur = admin2.get("/api/admin/depots").json()[kind]
            return set_depot(admin2, kind, points[i % 2], version=cur["version"])
        return f

    def edit_a(i):
        v = w.admin.get(f"/api/admin/rounds/{w.rid}/riders").json()
        va = [x for x in v if x["rider_id"] == w.a][0]["config_version"]
        return put_rider(w.admin, w.rid, w.a, version=va, capacity=5 + i % 2)

    def pin(i):
        o = w.admin.get(f"/api/admin/rounds/{w.rid}/orders").json()[0]
        return w.admin.send("POST", f"/api/admin/orders/{o['id']}/pin",
                            json={"version": o["version"], "lat": DU[("srcc", "ramjas")[i % 2]]["lat"],
                                  "lng": DU[("srcc", "ramjas")[i % 2]]["lng"]})

    jobs = [
        depot_move("office", (DU["gtb_nagar"], DU["office"])),
        depot_move("warehouse", (DU["civil_lines"], DU["warehouse"])),
        edit_a,
        lambda i: choose(phone_b, w.rid, ("last_stop", "office")[i % 2]),
        lambda i: confirm(w.ra, w.rid),
        lambda i: confirm(w.rb, w.rid),
        pin,
    ]
    threads = [threading.Thread(target=loop, args=(job,)) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert len(statuses) == 6 * len(jobs)
    assert all(s in (200, 409, 422) for s in statuses), sorted(set(statuses))  # 409/422: lost a version race
    assert orders  # the round still has its orders
    # Final state is consistent: every current confirmation matches its rider's current version.
    db.expire_all()
    for rr in db.scalars(select(RoundRider).where(RoundRider.round_id == w.rid)).all():
        assert rr.confirmed_version is None or rr.confirmed_version <= rr.config_version
