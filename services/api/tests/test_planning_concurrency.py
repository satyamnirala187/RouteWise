"""Real PostgreSQL concurrency for Phase 2B: stale solves never overwrite newer input, plan
commits and input edits serialise without deadlock, a failed commit rolls back completely,
unfinished runs are never reported as successful, and the work queue is bounded. An input
edit racing the commit's final check is serialised by the commit's round lock."""

import threading
import time
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, func, select, text

from routewise_api import accounts
from routewise_api.main import create_app
from routewise_api.models import DeliveryRound, PlanningRun, RoutePlan, User
from routewise_api import planning as planning_mod
from routewise_api.planning import PlanningService

from .planning_world import PUBLIC_DU, add_orders, optimize, orders_by_code, plan_now, wait_run
from .planning_world import world  # noqa: F401  (fixture)
from .test_concurrency import _wait_for_lock_waiters
from .test_round_setup import choose, confirm, put_rider, set_depot, setup_of


class Pause:
    """Holds the worker between solving and committing until released."""

    def __init__(self, service):
        self.reached, self.go = threading.Event(), threading.Event()
        service.hooks["after_solve"] = self

    def __call__(self, run_id):
        self.reached.set()
        assert self.go.wait(60)

    def wait(self):
        assert self.reached.wait(60), "worker never finished solving"


def owners(w) -> dict:
    return {c: o["planning"]["assigned_rider_id"] for c, o in orders_by_code(w).items()}


def plans(db, rid):
    db.expire_all()
    return [(p.version, p.is_current) for p in db.scalars(select(RoutePlan).where(RoutePlan.round_id == rid)
                                                            .order_by(RoutePlan.version)).all()]


def _destination(w):
    return choose(w.browsers["Rider C"], w.rid, "office")


def _status(w):
    o = orders_by_code(w)["RW-P004"]
    return w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "status": "Postponed"})


def _lock(w):
    o = orders_by_code(w)["RW-P004"]
    return w.admin.send("PUT", f"/api/admin/orders/{o['id']}/lock",
                        json={"version": o["version"], "rider_id": w.ids["Rider A"]})


def _priority(w):
    o = orders_by_code(w)["RW-P004"]
    return w.admin.send("PUT", f"/api/admin/orders/{o['id']}/priority",
                        json={"version": o["version"], "first_priority": True})


def _pin(w):
    o = orders_by_code(w)["RW-P004"]
    return w.admin.send("POST", f"/api/admin/orders/{o['id']}/pin",
                        json={"version": o["version"], "lat": PUBLIC_DU["ramjas"]["lat"],
                              "lng": PUBLIC_DU["ramjas"]["lng"]})


def _depot(w):
    office = w.admin.get("/api/admin/depots").json()["office"]
    return set_depot(w.admin, "office", PUBLIC_DU["gtb_nagar"], version=office["version"])


def _capacity(w):
    v = setup_of(w.browsers["Rider A"], w.rid).json()["config_version"]
    r = put_rider(w.admin, w.rid, w.ids["Rider A"], version=v, capacity=6)
    confirm(w.browsers["Rider A"], w.rid)  # even re-confirmed, the input changed during the solve
    return r


def _mode(w):
    return w.admin.send("PUT", f"/api/admin/rounds/{w.rid}/mode", json={"mode": "equal"})


def _deactivate(w):
    """The shared deactivation operation (used by the CLI): bumps input_version and the flag."""
    user_id = w.db.scalar(select(User.id).where(User.username == "rider_c"))
    with w.app.state.session_factory() as s:
        accounts.deactivate_user(s, user_id, w.app.state.clock())


def _account_flag(w):
    """A direct account-flag change that bypasses the shared operation: only the fingerprint sees it."""
    with w.app.state.session_factory() as s:
        s.execute(text("UPDATE users SET active = false WHERE username = 'rider_c'"))
        s.commit()


@pytest.mark.parametrize("change", [_destination, _status, _lock, _priority, _pin, _depot, _capacity, _mode, _deactivate,
                                    _account_flag], ids=lambda f: f.__name__.strip("_"))
def test_input_changed_during_the_solve_makes_the_run_stale_and_keeps_the_previous_plan(world, db, app, change):
    w = world
    plan_now(w)
    before = owners(w)
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    change(w)
    pause.go.set()
    run = wait_run(w, run_id)
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    assert plans(db, w.rid) == [(1, True)]
    after = owners(w)
    assert after == before  # no assignment touched by the stale result


def test_without_changes_the_paused_run_commits_the_next_version(world, db, app):
    w = world
    plan_now(w)
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    o = orders_by_code(w)["RW-P004"]  # customer text is not planning input
    w.admin.send("PATCH", f"/api/admin/orders/{o['id']}", json={"version": o["version"], "product": "Renamed parcel"})
    pause.go.set()
    assert wait_run(w, run_id)["state"] == "succeeded"
    assert plans(db, w.rid) == [(1, False), (2, True)]


def hold(db_url, sql, params):
    engine = create_engine(db_url)
    conn = engine.connect()
    tx = conn.begin()
    conn.execute(text(sql), params)
    return engine, conn, tx


def test_two_optimize_requests_for_one_round_start_one_run(world, db, db_url, app):
    w = world
    from .conftest import Browser

    other = Browser(app)
    other.login("admin1")
    pause = Pause(app.state.planning)
    engine, conn, tx = hold(db_url, "SELECT 1 FROM delivery_rounds WHERE id = :id FOR UPDATE", {"id": w.rid})
    results = [None, None]
    threads = [threading.Thread(target=lambda i=i, b=b: results.__setitem__(
        i, b.send("POST", f"/api/admin/rounds/{w.rid}/optimize"))) for i, b in enumerate((w.admin, other))]
    for t in threads:
        t.start()
    try:
        _wait_for_lock_waiters(engine, 2)
    finally:
        tx.rollback()
        conn.close()
    for t in threads:
        t.join(30)
    engine.dispose()
    assert sorted(r.status_code for r in results) == [202, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["detail"]["code"] == "RUN_IN_PROGRESS"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PlanningRun)) == 1
    pause.go.set()
    assert wait_run(w, next(r for r in results if r.status_code == 202).json()["id"])["state"] == "succeeded"


@pytest.mark.parametrize("edit", [_pin, _status, _depot, _destination], ids=["pin", "status", "depot", "destination"])
def test_plan_commit_racing_an_input_edit_serialises_without_deadlock(world, db, db_url, app, edit):
    """The commit and the edit both wait on the round row; whichever wins, the result is either a
    stale run (edit first) or a saved plan that is immediately out of date (commit first)."""
    w = world
    plan_now(w)
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    engine, conn, tx = hold(db_url, "SELECT 1 FROM delivery_rounds WHERE id = :id FOR UPDATE", {"id": w.rid})
    editor = threading.Thread(target=edit, args=(w,))
    pause.go.set()  # the worker now heads for the round lock
    editor.start()
    try:
        _wait_for_lock_waiters(engine, 2)
    finally:
        tx.rollback()
        conn.close()
    editor.join(30)
    engine.dispose()
    run = wait_run(w, run_id)
    assert run["state"] in ("stale", "succeeded"), run
    current = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    if run["state"] == "succeeded":
        assert current["version"] == 2 and current["out_of_date"] is True
    else:
        assert current["version"] == 1


class Gate:
    """Holds the worker inside its commit transaction, after the final input check and before any
    plan or assignment write (round, depot, run and account locks held)."""

    def __init__(self, service):
        self.reached, self.go = threading.Event(), threading.Event()
        service.hooks["before_write"] = self

    def __call__(self, run_id):
        self.reached.set()
        assert self.go.wait(60)


def _edit_committed_or_blocked(engine, editor, timeout: float = 10.0) -> bool:
    """True once the edit thread has finished (its change committed), False once it is waiting
    on a row lock."""
    end = time.monotonic() + timeout
    with engine.connect() as conn:
        while time.monotonic() < end:
            if not editor.is_alive():
                return True
            waiting = conn.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock'")).scalar_one()
            conn.rollback()
            if waiting >= 1:
                return False
            time.sleep(0.01)
    raise AssertionError("the edit neither finished nor blocked")


@pytest.mark.parametrize("edit", [_pin, _status, _lock, _priority, _destination, _capacity, _mode, _depot],
                         ids=lambda f: f.__name__.strip("_"))
def test_an_edit_racing_the_commit_after_its_final_check_has_a_serial_outcome(world, db, db_url, app, edit):
    """The commit has passed its final check and is about to write. A planning-input edit now
    either commits first (then the run must be stale and the previous assignments untouched) or
    after the plan (then the edit succeeds and the new plan is out of date). A plan that
    overwrites assignments after an earlier committed input change is never acceptable."""
    w = world
    plan_now(w)
    before = owners(w)
    gate = Gate(app.state.planning)
    run_id = optimize(w).json()["id"]
    assert gate.reached.wait(60), "worker never reached the final check"
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
    assert not editor.is_alive() and result["response"].status_code == 200, result
    run = wait_run(w, run_id)
    current = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    if edit_first:
        assert run["state"] == "stale", f"plan saved over an input change committed before it: {run}"
        assert current["version"] == 1 and owners(w) == before
    else:
        assert run["state"] == "succeeded", run
        assert current["version"] == 2 and current["out_of_date"] is True
        assert plans(db, w.rid) == [(1, False), (2, True)]
    # With the explicit round lock held by the commit, the edit cannot be first at this point.
    assert not edit_first


def test_a_round_the_deactivation_missed_still_cannot_get_a_valid_plan(world, db, db_url, app, monkeypatch):
    """Belt and braces for the account lock: even if a deactivation did not lock (or bump) a
    round the rider plans in, that round's commit reads the account FOR SHARE and so waits for
    the deactivation, then sees the inactive account and ends stale."""
    w = world
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    real = accounts.participating_rounds
    monkeypatch.setattr(accounts, "participating_rounds", lambda s, uid: real(s, uid) - {uuid.UUID(w.rid)})
    held = threading.Event()
    release = threading.Event()
    real_revoke = accounts.revoke_sessions

    def revoke_then_hold(s, user_id, now):
        n = real_revoke(s, user_id, now)
        held.set()
        assert release.wait(60)
        return n

    monkeypatch.setattr(accounts, "revoke_sessions", revoke_then_hold)
    user_id = db.scalar(select(User.id).where(User.username == "rider_c"))

    def deactivate():
        with app.state.session_factory() as s:
            accounts.deactivate_user(s, user_id, app.state.clock())

    t = threading.Thread(target=deactivate)
    t.start()
    assert held.wait(30)
    pause.go.set()
    engine = create_engine(db_url)
    try:
        _wait_for_lock_waiters(engine, 1)  # the commit waits on the account row
    finally:
        release.set()
        engine.dispose()
    t.join(30)
    run = wait_run(w, run_id)
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(RoutePlan)) == 0


def test_a_failed_commit_rolls_back_completely(world, db, app, monkeypatch):
    w = world
    plan_now(w)
    before = owners(w)
    real = planning_mod.commit_plan

    def explode(*args, **kwargs):
        real(*args, **kwargs)  # every plan row and assignment is written, then the commit fails
        raise RuntimeError("simulated failure after writing")

    monkeypatch.setattr(planning_mod, "commit_plan", explode)
    w.admin.send("PUT", f"/api/admin/rounds/{w.rid}/mode", json={"mode": "equal"})
    run = wait_run(w, optimize(w).json()["id"])
    assert run["state"] == "failed" and run["error"]["code"] == "INTERNAL"
    assert plans(db, w.rid) == [(1, True)] and owners(w) == before
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(RoutePlan)) == 1


def _insert_run(db, rid, state, requested_at):
    admin_id = db.scalar(select(User.id).where(User.username == "admin1"))
    run = PlanningRun(round_id=rid, state=state, requested_by=admin_id, requested_at=requested_at, input_version=1,
                      input_fingerprint="0" * 64, mode="smart")
    db.add(run)
    db.commit()
    return run.id


def test_unfinished_runs_are_marked_interrupted_on_restart(world, db, settings, clock):
    w = world
    run_id = _insert_run(db, w.rid, "running", clock())
    app2 = create_app(settings, clock=clock)
    try:
        db.expire_all()
        run = db.get(PlanningRun, run_id)
        assert run.state == "interrupted" and run.error_code == "INTERRUPTED" and run.finished_at is not None
        assert db.scalar(select(func.count()).select_from(RoutePlan)) == 0
    finally:
        app2.state.planning.shutdown()
        app2.state.engine.dispose()
    assert optimize(w).status_code == 202  # the round is free again


def test_overdue_runs_are_reported_interrupted_never_successful(world, db, clock, app):
    w = world
    run_id = _insert_run(db, w.rid, "queued", clock() - timedelta(hours=2))
    run = w.admin.get(f"/api/admin/planning-runs/{run_id}").json()
    assert run["state"] == "interrupted" and run["error"]["code"] == "INTERRUPTED" and run["plan_version"] is None


def _second_round(w, db):
    owner = db.scalar(select(User).where(User.username == "admin1"))
    rnd = DeliveryRound(name="Second synthetic round", created_by=owner.id)
    db.add(rnd)
    db.commit()
    add_orders(db, rnd.id, ["kirori_mal", "ramjas"], start=50)
    rid = str(rnd.id)
    put_rider(w.admin, rid, w.ids["Rider A"], capacity=5, start="office")
    choose(w.browsers["Rider A"], rid, "last_stop")
    confirm(w.browsers["Rider A"], rid)
    return rid


def test_the_work_queue_is_bounded(world, db, app):
    w = world
    old = app.state.planning
    old.shutdown()
    limits = replace(app.state.settings.planning, workers=1, queue_size=0)
    service = PlanningService(replace(app.state.settings, planning=limits), app.state.session_factory, app.state.clock)
    service.provider_override = w.provider
    app.state.planning = service
    pause = Pause(service)
    first = optimize(w)
    assert first.status_code == 202
    pause.wait()
    rid2 = _second_round(w, db)
    busy = w.admin.send("POST", f"/api/admin/rounds/{rid2}/optimize")
    assert busy.status_code == 503 and busy.json()["detail"]["code"] == "PLANNING_BUSY"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PlanningRun).where(PlanningRun.round_id == rid2)) == 0
    pause.go.set()
    assert wait_run(w, first.json()["id"])["state"] == "succeeded"
    service.hooks.clear()
    later = w.admin.send("POST", f"/api/admin/rounds/{rid2}/optimize")
    assert later.status_code == 202 and wait_run(w, later.json()["id"])["state"] == "succeeded"


def test_the_database_allows_one_active_run_per_round(world, db, clock):
    w = world
    _insert_run(db, w.rid, "queued", clock())
    with pytest.raises(Exception):
        _insert_run(db, w.rid, "running", clock())
    db.rollback()
    r = optimize(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "RUN_IN_PROGRESS"
