"""Real PostgreSQL concurrency: import transitions are atomic, and a failed commit is never
reported as success. Races are made deterministic: an outside connection holds the batch row
lock until BOTH requests are blocked on PostgreSQL locks, then releases it so they race."""

import threading
import time

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from routewise_api.models import DeliveryRound, ImportBatch, Order

from .conftest import HEADER, PIN, Browser, make_user, upload, xlsx

ROWS = [HEADER] + [[f"Test Customer C{i}", "Box", f"0000000{i:04d}", PIN, None] for i in range(5)]


def _wait_for_lock_waiters(engine, n: int, timeout: float = 10.0) -> None:
    with engine.connect() as conn:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            waiting = conn.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock'")).scalar_one()
            conn.rollback()  # pg_stat_activity is snapshotted per transaction; take a fresh one each poll
            if waiting >= n:
                return
            time.sleep(0.02)
    raise AssertionError(f"expected {n} requests blocked on a row lock")


def race(app, db_url, import_id, calls):
    """Hold the batch row lock, start all calls, wait until they all block, release, collect."""
    engine = create_engine(db_url)
    holder = engine.connect()
    tx = holder.begin()
    holder.execute(text("SELECT 1 FROM import_batches WHERE id = :id FOR UPDATE"), {"id": import_id})
    results = [None] * len(calls)

    def run(i, fn):
        results[i] = fn()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    try:
        _wait_for_lock_waiters(engine, len(calls))
    finally:
        tx.rollback()  # release: the requests now race for the row
        holder.close()
    for t in threads:
        t.join(timeout=30)
    engine.dispose()
    return results


@pytest.fixture
def two_admins(app):
    make_user(app, "admin1", "admin")
    a, b = Browser(app), Browser(app)
    assert a.login("admin1").status_code == 200 and b.login("admin1").status_code == 200
    return a, b


def counts(db):
    db.expire_all()
    return (db.scalar(select(func.count()).select_from(DeliveryRound)),
            db.scalar(select(func.count()).select_from(Order)))


def test_two_simultaneous_commits_create_exactly_one_round(app, db, db_url, two_admins):
    a, b = two_admins
    pid = upload(a, xlsx(ROWS)).json()["id"]
    r1, r2 = race(app, db_url, pid, [lambda: a.send("POST", f"/api/admin/imports/{pid}/commit"),
                                      lambda: b.send("POST", f"/api/admin/imports/{pid}/commit")])
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409], statuses
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["detail"] == "This import was already saved or discarded"
    assert counts(db) == (1, 5)
    codes = db.scalars(select(Order.order_code)).all()
    assert len(codes) == len(set(codes)) == 5
    assert db.get(ImportBatch, pid).state == "committed"


def test_commit_racing_discard_cannot_both_succeed(app, db, db_url, two_admins):
    a, b = two_admins
    for _ in range(3):  # either side may win; the invariant must hold every time
        pid = upload(a, xlsx(ROWS)).json()["id"]
        before = counts(db)
        commit, discard = race(app, db_url, pid, [lambda: a.send("POST", f"/api/admin/imports/{pid}/commit"),
                                                   lambda: b.send("DELETE", f"/api/admin/imports/{pid}")])
        assert sorted([commit.status_code, discard.status_code]) == [200, 409]
        db.expire_all()
        state = db.get(ImportBatch, pid).state
        if commit.status_code == 200:
            assert state == "committed" and counts(db) == (before[0] + 1, before[1] + 5)
            assert discard.json()["detail"] == "Only a preview can be discarded"
        else:
            assert state == "discarded" and counts(db) == before
            assert commit.json()["detail"] == "This import was already saved or discarded"
        assert db.get(ImportBatch, pid).rows is None


def test_expired_preview_cannot_be_committed_by_a_racing_request(app, db, db_url, two_admins, clock):
    a, b = two_admins
    pid = upload(a, xlsx(ROWS)).json()["id"]
    clock.advance(hours=2)
    r1, r2 = race(app, db_url, pid, [lambda: a.send("POST", f"/api/admin/imports/{pid}/commit"),
                                      lambda: b.send("POST", f"/api/admin/imports/{pid}/commit")])
    assert sorted([r1.status_code, r2.status_code]) in ([409, 410], [410, 410])
    assert counts(db) == (0, 0) and db.get(ImportBatch, pid).state == "discarded"


def test_failed_commit_is_never_reported_as_success(app, admin, db):
    pid = upload(admin, xlsx(ROWS[:2])).json()["id"]
    real = app.state.session_factory

    class FailingCommit(Session):
        def commit(self):
            raise OperationalError("COMMIT", {}, Exception("simulated commit failure"))

    # raise_server_exceptions is fixed when a TestClient is built, so use a fresh client with the same session.
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("rw_session", admin.client.cookies.get("rw_session"))
    app.state.session_factory = sessionmaker(bind=app.state.engine, class_=FailingCommit, expire_on_commit=False)
    try:
        r = client.post(f"/api/admin/imports/{pid}/commit", headers=admin.headers())
    finally:
        app.state.session_factory = real
    assert r.status_code == 500  # the commit runs before the response, so failure is visible
    assert counts(db) == (0, 0) and db.get(ImportBatch, pid).state == "preview"
