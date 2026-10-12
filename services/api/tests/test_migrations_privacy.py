"""Migrations round-trip and match the models; customer data stays out of logs and error echoes."""

import logging

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from routewise_api.models import Base

from .conftest import HEADER, PIN, alembic_config, reset_schema, upload, xlsx

EXPECTED_TABLES = {"users", "riders", "sessions", "login_failures", "import_batches", "delivery_rounds",
                   "orders", "assignments", "alembic_version"}


def test_migrations_upgrade_downgrade_upgrade_and_match_models(db_url):
    reset_schema(db_url)
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    eng = create_engine(db_url)
    assert set(inspect(eng).get_table_names()) == EXPECTED_TABLES
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        assert diff == [], diff
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001"
        checks = {r[0] for r in conn.execute(text("SELECT conname FROM pg_constraint WHERE contype = 'c'"))}
        assert {"ck_orders_status", "ck_users_role", "ck_orders_resolved_has_coords"} <= checks
    command.downgrade(cfg, "base")
    assert set(inspect(eng).get_table_names()) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert set(inspect(eng).get_table_names()) == EXPECTED_TABLES
    eng.dispose()


SECRETS = ["Test Customer Privacy", "00000077777", "Privacy Product", "Use the side door"]


def test_customer_details_never_reach_logs(admin, caplog):
    caplog.set_level(logging.DEBUG)  # every logger, every level
    data = xlsx([HEADER, [SECRETS[0], SECRETS[2], SECRETS[1], PIN, SECRETS[3]],
                 [SECRETS[0], SECRETS[2], "bad contact!", PIN, None]])
    p = upload(admin, data).json()
    admin.send("POST", f"/api/admin/imports/{p['id']}/commit")
    rid = admin.get("/api/admin/rounds").json()
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert not any(s in log_text for s in SECRETS)


def test_validation_errors_do_not_echo_submitted_values(admin):
    r = admin.send("PATCH", "/api/admin/orders/00000000-0000-0000-0000-000000000000",
                   json={"version": "not-a-number", "contact": "00000077777"})
    assert r.status_code == 422 and "00000077777" not in r.text and "not-a-number" not in r.text


def test_api_responses_are_not_cacheable(admin):
    r = admin.get("/api/admin/rounds")
    assert r.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_spa_fallback_never_serves_files_outside_the_build(app):
    """With a built frontend, unknown paths get index.html; traversal never reaches repo files."""
    import pytest
    from fastapi.testclient import TestClient

    from routewise_api.main import WEB_DIST

    if not WEB_DIST.is_dir():
        pytest.skip("frontend not built (npm run build); SPA fallback inactive")
    c = TestClient(app)
    for path in ("/%2e%2e/%2e%2e/%2e%2e/.env", "/..%2f..%2f..%2f.env", "/%2e%2e/%2e%2e/%2e%2e/services/api/alembic.ini",
                 "/assets/..%2f..%2f..%2f..%2f.env"):
        r = c.get(path)
        assert "ROUTEWISE_SECRET_KEY" not in r.text and "DATABASE_URL" not in r.text and "sqlalchemy" not in r.text, path
    assert "<title>RouteWise</title>" in c.get("/admin/import").text
    assert c.get("/api/not-a-route").status_code == 404
