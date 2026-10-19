"""Schema check and explicit upgrade for the isolated phone-test database (local only).
See docs/phase3/PHONE-TEST-GUIDE.md.

    services/api/.venv/bin/python services/api/scripts/phone_db.py check      # read-only; scripts/phone-server.sh runs it
    services/api/.venv/bin/python services/api/scripts/phone_db.py upgrade    # you run it; keeps the data

Only the database `routewise_phone` is ever read or changed (any other name is refused).

`check` compares the database's migration revision with the one this code expects and, when they
differ, prints what to do. It runs in a read-only transaction and never changes anything.

`upgrade` applies the missing migrations to `routewise_phone` and nothing else. Migrations only
add to the schema (4B adds columns with defaults, plus tables), so the riders, orders, plan and
statuses already in the database are kept. It never drops, resets or rebuilds: that is what
phone_setup.py does, and it is a separate, explicit command. Without a database at an older known
revision, `upgrade` refuses and changes nothing.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from routewise_api.config import load_settings  # noqa: E402

DB_NAME = "routewise_phone"
PY = "services/api/.venv/bin/python"
UPGRADE_CMD = f"{PY} services/api/scripts/phone_db.py upgrade"
SETUP_CMD = f"{PY} services/api/scripts/phone_setup.py"


@dataclass(frozen=True)
class SchemaState:
    kind: str  # current | outdated | uninitialised | unknown | unreachable
    current: str | None
    head: str


def phone_db_url() -> str:
    base = os.environ.get("DATABASE_URL", "")
    if not base:
        raise SystemExit("DATABASE_URL is not set (run scripts/dev-db.sh init)")
    url = base.rsplit("/", 1)[0] + "/" + DB_NAME
    if not url.endswith("/" + DB_NAME):
        raise SystemExit("refusing: not the routewise_phone database")
    return url


def alembic_config(url: str) -> Config:
    cfg = Config(str(API / "alembic.ini"))
    cfg.set_main_option("script_location", str(API / "migrations"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={url}"]})()
    return cfg


def schema_state(url: str) -> SchemaState:
    """Where the database is relative to this code's migrations. Read-only."""
    script = ScriptDirectory.from_config(alembic_config(url))
    head = script.get_current_head()
    known = {r.revision for r in script.walk_revisions()}
    try:
        eng = create_engine(url)
        with eng.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))  # first statement of the transaction; `check` cannot write
            current = MigrationContext.configure(conn).get_current_revision()
        eng.dispose()
    except OperationalError:  # server stopped, or the database does not exist; the driver's text is not echoed
        return SchemaState("unreachable", None, head)
    if current is None:
        return SchemaState("uninitialised", None, head)
    if current == head:
        return SchemaState("current", current, head)
    return SchemaState("outdated" if current in known else "unknown", current, head)


def explain(state: SchemaState) -> str:
    """What the owner should do, for a state that is not `current`."""
    if state.kind == "outdated":
        return (f"The phone-test database {DB_NAME} is on schema {state.current}, but this code needs {state.head}.\n"
                "Nothing was changed.\n\n"
                f"To upgrade ONLY {DB_NAME} and keep its data (riders, orders, plan, statuses), run from the RouteWise folder:\n"
                f"    {UPGRADE_CMD}\n"
                "then start the server again. The development and test databases are never touched.\n\n"
                f"(Only if you want fresh data and passwords instead: {SETUP_CMD} rebuilds {DB_NAME} from scratch. "
                "That DELETES what is in it.)")
    if state.kind == "uninitialised":
        return (f"The phone-test database {DB_NAME} has no RouteWise schema yet. Nothing was changed.\n"
                f"Build it (first time) from the RouteWise folder:\n    {SETUP_CMD}")
    if state.kind == "unknown":
        return (f"The phone-test database {DB_NAME} is on schema {state.current}, which this code does not know "
                f"(it knows up to {state.head}). Nothing was changed.\n"
                "It was probably built by newer code. Check out the matching version, or rebuild it with fresh data "
                f"(this DELETES what is in it):\n    {SETUP_CMD}")
    return (f"The phone-test database {DB_NAME} cannot be reached. Nothing was changed.\n"
            "Start the local database, then create the database if this is the first time:\n"
            "    scripts/dev-db.sh start\n"
            f"    scripts/dev-db.sh create-db {DB_NAME}\n"
            f"    {SETUP_CMD}")


def upgrade(url: str, db_name: str = DB_NAME) -> SchemaState:
    """Apply the missing migrations to `db_name` only. `db_name` is a parameter solely so the test
    suite can exercise this on its own scratch database; the command line always passes routewise_phone."""
    before = schema_state(url)
    if before.kind != "outdated":
        return before
    eng = create_engine(url)
    with eng.connect() as conn:
        if conn.execute(text("SELECT current_database()")).scalar_one() != db_name:
            raise SystemExit(f"refusing: connected to a database other than {db_name}")
    eng.dispose()
    print(f"Upgrading {db_name} from {before.current} to {before.head} (data is kept) …")
    command.upgrade(alembic_config(url), "head")  # PostgreSQL DDL is transactional: a failed step rolls back
    return schema_state(url)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("check", "upgrade"):
        print(__doc__)
        return 2
    load_settings()  # loads the git-ignored .env into os.environ
    url = phone_db_url()
    if argv[0] == "check":
        state = schema_state(url)
        if state.kind == "current":
            print(f"Database {DB_NAME}: schema {state.current} (current).")
            return 0
        print(explain(state))
        return 1
    state = upgrade(url)
    if state.kind == "current":
        print(f"Database {DB_NAME}: schema {state.current} (current). Start the server with scripts/phone-server.sh.")
        return 0
    print(explain(state))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
