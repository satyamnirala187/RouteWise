"""Account deactivation and plan validity (real PostgreSQL). Deactivation goes through the CLI,
which uses the shared `accounts.deactivate_user` operation: sessions end, every round the rider
participates in gets a new input_version (saved plans become out of date, in-flight runs end
stale), and it serialises with the plan commit's final check. Ownership and Completed history
are kept. Password and display-name changes invalidate nothing."""

import io
import threading
import uuid

from sqlalchemy import create_engine, select

from routewise_api import accounts
from routewise_api import cli
from routewise_api.models import Assignment, DeliveryRound, Order, User

from .planning_world import optimize, orders_by_code, plan_now, wait_run
from .planning_world import world  # noqa: F401  (fixture)
from .test_concurrency import _wait_for_lock_waiters
from .test_planning_concurrency import Pause, owners, plans


class Gate:
    """Blocks the caller at a chosen point until released."""

    def __init__(self):
        self.reached, self.go = threading.Event(), threading.Event()

    def __call__(self, *args):
        self.reached.set()
        assert self.go.wait(60)

    def wait(self):
        assert self.reached.wait(60), "gate never reached"


def run_cli(monkeypatch, settings, *argv, stdin=""):
    monkeypatch.setattr("routewise_api.cli.load_settings", lambda: settings)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert cli.main(list(argv)) == 0


class CliThread(threading.Thread):
    """Runs a CLI command in the background and keeps its failure for the test to re-raise."""

    def __init__(self, monkeypatch, settings, *argv):
        super().__init__()
        self.args, self.error = (monkeypatch, settings, *argv), None

    def run(self):
        try:
            run_cli(*self.args)
        except BaseException as exc:  # noqa: BLE001
            self.error = exc

    def finish(self):
        self.join(30)
        assert not self.is_alive(), "deactivation never finished"
        if self.error:
            raise self.error


def plan_flags(w) -> dict:
    """Validity as every plan response reports it: current plan, history list, each version."""
    current = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    history = w.admin.get(f"/api/admin/rounds/{w.rid}/plans").json()
    by_version = {p["version"]: w.admin.get(f"/api/admin/rounds/{w.rid}/plans/{p['version']}").json()["out_of_date"]
                  for p in history}
    return {"current": (current["version"], current["out_of_date"]),
            "history": [(p["version"], p["is_current"], p["out_of_date"]) for p in history],
            "versions": by_version}


def input_version(db, rid) -> int:
    db.expire_all()
    return db.get(DeliveryRound, rid).input_version


def test_deactivating_a_rider_after_a_saved_plan_marks_it_out_of_date(world, db, settings, monkeypatch, capsys):
    w = world
    plan_now(w)
    assert plan_flags(w)["current"] == (1, False)
    before, version = owners(w), input_version(db, w.rid)
    run_cli(monkeypatch, settings, "deactivate", "--username", "rider_c")
    assert "planning input changed in 1 round(s)" in capsys.readouterr().out
    assert input_version(db, w.rid) == version + 1
    assert plan_flags(w) == {"current": (1, True), "history": [(1, True, True)], "versions": {1: True}}
    assert owners(w) == before  # ownership is kept; the round needs re-planning
    assert w.browsers["Rider C"].get("/api/rider/rounds").status_code == 401  # sessions end as before
    readiness = w.admin.get(f"/api/admin/rounds/{w.rid}/readiness").json()
    assert not readiness["ready"] and "account_inactive" in {b["code"] for b in readiness["configuration_blockers"]}
    refused = optimize(w)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "NOT_READY"


def test_deactivation_keeps_postponed_ownership_and_completed_history(world, db, settings, monkeypatch):
    w = world
    for code in ("RW-P005", "RW-P006"):
        o = orders_by_code(w)[code]
        assert w.admin.send("PUT", f"/api/admin/orders/{o['id']}/lock",
                            json={"version": o["version"], "rider_id": w.ids["Rider C"]}).status_code == 200
    plan_now(w)
    for code, status in (("RW-P005", "Postponed"), ("RW-P006", "Completed")):
        o = orders_by_code(w)[code]
        assert w.admin.send("PATCH", f"/api/admin/orders/{o['id']}",
                            json={"version": o["version"], "status": status}).status_code == 200
    plan = plan_now(w)  # v2 holds both for Rider C
    route_c = next(r for r in plan["routes"] if r["rider_id"] == w.ids["Rider C"])
    assert [o["order_code"] for o in route_c["postponed"]] == ["RW-P005"]
    assert [o["order_code"] for o in route_c["completed"]] == ["RW-P006"]
    before = owners(w)
    run_cli(monkeypatch, settings, "deactivate", "--username", "rider_c")
    assert plan_flags(w)["current"] == (2, True)
    assert owners(w) == before
    db.expire_all()
    rows = {o.order_code: (o.status, a.rider_id) for o, a in db.execute(
        select(Order, Assignment).join(Assignment, Assignment.order_id == Order.id)
        .where(Order.order_code.in_(["RW-P005", "RW-P006"]))).all()}
    assert {c: (s, str(r)) for c, (s, r) in rows.items()} == {
        "RW-P005": ("Postponed", w.ids["Rider C"]), "RW-P006": ("Completed", w.ids["Rider C"])}


def test_password_and_display_name_changes_do_not_invalidate_plans(world, db, settings, monkeypatch, app):
    w = world
    plan_now(w)
    version = input_version(db, w.rid)
    run_cli(monkeypatch, settings, "set-password", "--username", "rider_a", stdin="another long password\n")
    profile = next(r for r in w.admin.get("/api/admin/riders").json() if r["id"] == w.ids["Rider B"])
    assert w.admin.send("PATCH", f"/api/admin/riders/{w.ids['Rider B']}",
                        json={"version": profile["version"], "display_name": "Rider B renamed"}).status_code == 200
    assert input_version(db, w.rid) == version
    assert plan_flags(w)["current"] == (1, False)
    # ...and neither change makes an in-flight run stale.
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    run_cli(monkeypatch, settings, "set-password", "--username", "rider_b", stdin="yet another long password\n")
    profile = next(r for r in w.admin.get("/api/admin/riders").json() if r["id"] == w.ids["Rider A"])
    assert w.admin.send("PATCH", f"/api/admin/riders/{w.ids['Rider A']}",
                        json={"version": profile["version"], "display_name": "Rider A renamed"}).status_code == 200
    pause.go.set()
    assert wait_run(w, run_id)["state"] == "succeeded"
    assert plan_flags(w)["current"] == (2, False)


def test_deactivation_during_solving_makes_the_run_stale(world, db, settings, monkeypatch, app):
    w = world
    plan_now(w)
    before = owners(w)
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    run_cli(monkeypatch, settings, "deactivate", "--username", "rider_c")
    pause.go.set()
    run = wait_run(w, run_id)
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    assert plans(db, w.rid) == [(1, True)]
    assert plan_flags(w) == {"current": (1, True), "history": [(1, True, True)], "versions": {1: True}}
    assert owners(w) == before


def test_deactivation_during_the_final_check_waits_for_the_commit(world, db, db_url, settings, monkeypatch, app):
    """Commit first: the worker has passed its final check (round and user rows locked) and is
    about to write. The deactivation must wait, then mark the new plan out of date."""
    w = world
    plan_now(w)
    gate = Gate()
    app.state.planning.hooks["before_write"] = gate
    run_id = optimize(w).json()["id"]
    gate.wait()
    deactivation = CliThread(monkeypatch, settings, "deactivate", "--username", "rider_c")
    deactivation.start()
    engine = create_engine(db_url)
    try:
        _wait_for_lock_waiters(engine, 1)
        assert deactivation.is_alive()
        db.expire_all()
        assert db.scalar(select(User.active).where(User.username == "rider_c")) is True
    finally:
        gate.go.set()
        engine.dispose()
    deactivation.finish()
    assert wait_run(w, run_id)["state"] == "succeeded"
    assert plans(db, w.rid) == [(1, False), (2, True)]
    assert plan_flags(w) == {"current": (2, True), "history": [(2, True, True), (1, False, True)],
                             "versions": {1: True, 2: True}}
    db.expire_all()
    assert db.scalar(select(User.active).where(User.username == "rider_c")) is False


def test_a_commit_waits_for_an_uncommitted_deactivation_and_ends_stale(world, db, db_url, settings, monkeypatch, app):
    """Deactivation first: it holds the round and user rows (bump done, not yet committed) when
    the worker reaches its final check. The worker must wait, then see the change."""
    w = world
    plan_now(w)
    before = owners(w)
    pause = Pause(app.state.planning)
    run_id = optimize(w).json()["id"]
    pause.wait()
    gate = Gate()
    real_revoke = accounts.revoke_sessions

    def revoke_then_hold(db_, user_id, now):
        n = real_revoke(db_, user_id, now)
        gate()
        return n

    monkeypatch.setattr(accounts, "revoke_sessions", revoke_then_hold)
    deactivation = CliThread(monkeypatch, settings, "deactivate", "--username", "rider_c")
    deactivation.start()
    gate.wait()
    pause.go.set()  # the worker heads for the round lock held by the deactivation
    engine = create_engine(db_url)
    try:
        _wait_for_lock_waiters(engine, 1)
        run = w.admin.get(f"/api/admin/planning-runs/{run_id}").json()
        assert run["state"] == "running"
    finally:
        gate.go.set()
        engine.dispose()
    deactivation.finish()
    run = wait_run(w, run_id)
    assert run["state"] == "stale" and run["error"]["code"] == "INPUTS_CHANGED"
    assert plans(db, w.rid) == [(1, True)]
    assert plan_flags(w)["current"] == (1, True)
    assert owners(w) == before


def test_deactivation_retries_when_the_rider_joins_a_round_meanwhile(world, db, monkeypatch, clock):
    w = world
    plan_now(w)
    version = input_version(db, w.rid)
    real = accounts.participating_rounds
    calls = []

    def first_read_misses_the_round(db_, user_id):
        calls.append(1)
        return set() if len(calls) == 1 else real(db_, user_id)

    monkeypatch.setattr(accounts, "participating_rounds", first_read_misses_the_round)
    user_id = db.scalar(select(User.id).where(User.username == "rider_c"))
    with w.app.state.session_factory() as s:
        done = accounts.deactivate_user(s, user_id, clock())
    assert len(calls) >= 3  # initial read, recheck that found the round, recheck after relocking
    assert done.changed and done.rounds_invalidated == (uuid.UUID(w.rid),)
    assert input_version(db, w.rid) == version + 1
    assert plan_flags(w)["current"] == (1, True)


def test_deactivating_an_inactive_or_admin_account_changes_no_round(world, db, clock):
    w = world
    plan_now(w)
    version = input_version(db, w.rid)
    factory = w.app.state.session_factory
    rider = db.scalar(select(User.id).where(User.username == "rider_c"))
    with factory() as s:
        assert accounts.deactivate_user(s, rider, clock()).changed
    with factory() as s:
        again = accounts.deactivate_user(s, rider, clock())
    assert not again.changed and again.rounds_invalidated == ()
    assert input_version(db, w.rid) == version + 1  # bumped once, not twice
    admin = db.scalar(select(User.id).where(User.username == "admin1"))
    with factory() as s:
        done = accounts.deactivate_user(s, admin, clock())
    assert done.changed and done.rounds_invalidated == () and done.sessions_revoked >= 1
    assert input_version(db, w.rid) == version + 1
