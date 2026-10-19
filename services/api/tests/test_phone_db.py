"""Phone-test database schema preflight (4B): an out-of-date database gets instructions, never a silent change.

`scripts/phone_db.py` is exercised on the test database (never on routewise_phone); synthetic rows only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from .conftest import alembic_config, reset_schema

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def phone_db():
    spec = importlib.util.spec_from_file_location("phone_db", REPO / "services" / "api" / "scripts" / "phone_db.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["phone_db"] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("phone_db", None)


@pytest.fixture
def scratch(db_url):
    """The test database, empty; restored to the current schema afterwards for the other tests."""
    reset_schema(db_url)
    yield db_url
    reset_schema(db_url)
    command.upgrade(alembic_config(db_url), "head")


def _revision(url: str) -> str | None:
    eng = create_engine(url)
    with eng.connect() as conn:
        if "alembic_version" not in inspect(conn).get_table_names():
            eng.dispose()
            return None
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    eng.dispose()
    return rev


def _seed_at_0004(url: str) -> None:
    """A rider's round as the phone database held it before 4B (raw SQL: the models are at head)."""
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (id, username, role, password_hash) VALUES
              ('00000000-0000-0000-0000-0000000000a1', 'upgrade_admin', 'admin', 'x'),
              ('00000000-0000-0000-0000-0000000000b1', 'upgrade_rider', 'rider', 'x');
            INSERT INTO riders (id, user_id, display_name, vehicle)
              VALUES ('00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000b1', 'Upgrade Rider', 'scooter');
            INSERT INTO delivery_rounds (id, name, created_by)
              VALUES ('00000000-0000-0000-0000-0000000000d1', 'Upgrade round', '00000000-0000-0000-0000-0000000000a1');
            INSERT INTO round_riders (round_id, rider_id, vehicle, capacity, start_kind)
              VALUES ('00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-0000000000c1', 'scooter', 4, 'office');
            """))
    eng.dispose()


def test_a_current_database_passes(phone_db, db_url):
    state = phone_db.schema_state(db_url)
    assert state.kind == "current" and state.current == state.head == "0005"


def test_an_outdated_database_is_reported_with_instructions_and_left_unchanged(phone_db, scratch):
    command.upgrade(alembic_config(scratch), "0004")
    _seed_at_0004(scratch)
    state = phone_db.schema_state(scratch)
    assert (state.kind, state.current, state.head) == ("outdated", "0004", "0005")
    text_ = phone_db.explain(state)
    assert "0004" in text_ and "0005" in text_ and "Nothing was changed" in text_
    assert phone_db.UPGRADE_CMD in text_ and "ONLY routewise_phone" in text_ and "keep its data" in text_
    assert "DELETES" in text_  # the rebuild is offered only as a clearly labelled alternative
    assert _revision(scratch) == "0004"  # the check changed nothing
    eng = create_engine(scratch)
    assert "route_version" not in {c["name"] for c in inspect(eng).get_columns("round_riders")}
    eng.dispose()


def test_upgrade_keeps_the_data_and_only_adds(phone_db, scratch):
    command.upgrade(alembic_config(scratch), "0004")
    _seed_at_0004(scratch)
    name = make_url(scratch).database
    state = phone_db.upgrade(scratch, db_name=name)
    assert state.kind == "current" and state.current == "0005"
    eng = create_engine(scratch)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 2
        assert conn.execute(text("SELECT display_name FROM riders")).scalar_one() == "Upgrade Rider"
        assert conn.execute(text("SELECT name FROM delivery_rounds")).scalar_one() == "Upgrade round"
        rr = conn.execute(text("SELECT vehicle, capacity, config_version, route_version FROM round_riders")).one()
        assert tuple(rr) == ("scooter", 4, 1, 1)  # existing row kept; the new column takes its default
    eng.dispose()
    assert phone_db.schema_state(scratch).kind == "current"
    assert phone_db.upgrade(scratch, db_name=name).kind == "current"  # nothing left to do


def test_upgrade_refuses_a_database_that_is_not_the_named_one(phone_db, scratch):
    command.upgrade(alembic_config(scratch), "0004")
    with pytest.raises(SystemExit, match="refusing"):
        phone_db.upgrade(scratch, db_name="routewise_phone")  # the guard compares the connected database
    assert _revision(scratch) == "0004"


def test_an_uninitialised_database_is_reported_and_not_touched(phone_db, scratch):
    state = phone_db.schema_state(scratch)
    assert state.kind == "uninitialised" and "phone_setup.py" in phone_db.explain(state)
    assert phone_db.upgrade(scratch, db_name=make_url(scratch).database).kind == "uninitialised"
    assert _revision(scratch) is None  # not even the version table was created


def test_an_unknown_revision_is_reported_and_not_touched(phone_db, scratch):
    eng = create_engine(scratch)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('9999')"))
    eng.dispose()
    state = phone_db.schema_state(scratch)
    assert state.kind == "unknown" and state.current == "9999" and "does not know" in phone_db.explain(state)
    assert phone_db.upgrade(scratch, db_name=make_url(scratch).database).kind == "unknown"
    assert _revision(scratch) == "9999"


def test_a_missing_database_is_reported_without_echoing_the_connection(phone_db, db_url):
    missing = make_url(db_url).set(database="routewise_missing_for_preflight_test")
    state = phone_db.schema_state(missing.render_as_string(hide_password=False))
    assert state.kind == "unreachable"
    message = phone_db.explain(state)
    assert "create-db routewise_phone" in message and make_url(db_url).password not in message


def test_the_launcher_runs_the_preflight_before_building_or_serving():
    script = (REPO / "scripts" / "phone-server.sh").read_text()
    check = script.index("phone_db.py\" check")
    assert check < script.index("npm run") and check < script.index("exec ")
    assert "upgrade" not in script.split("phone_db.py\" check")[1].split("echo \"Building")[0]  # it never migrates
