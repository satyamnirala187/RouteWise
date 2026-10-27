"""The HTML document the phone loads carries the Permissions-Policy that lets the rider's own page use location.

Root cause of the Android GPS blocker: the header was `geolocation=()`, which disables location even on http://localhost.
These tests read the real response headers of the SPA documents served by FastAPI (a temporary build, so they do not
depend on `npm run build`)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from routewise_api.main import SECURITY_HEADERS, create_app

LOCATION_FOR_OWN_ORIGIN = "geolocation=(self), camera=(), microphone=()"


@pytest.fixture
def web(settings, clock, tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("//")
    (tmp_path / "index.html").write_text("<!doctype html><title>RouteWise</title>")
    monkeypatch.setattr("routewise_api.main.WEB_DIST", tmp_path)
    app = create_app(settings, clock=clock)
    yield TestClient(app)
    app.state.planning.shutdown()
    app.state.engine.dispose()


def test_policy_allows_location_for_the_own_origin_only():
    assert SECURITY_HEADERS["Permissions-Policy"] == LOCATION_FOR_OWN_ORIGIN
    assert "*" not in SECURITY_HEADERS["Permissions-Policy"]


@pytest.mark.parametrize("path", ["/", "/index.html", "/login", "/rider", "/rider/rounds/0b6c1c2e", "/admin/orders", "/no/such/deep/link"])
def test_every_html_document_and_spa_deep_link_carries_the_policy_and_the_other_security_headers(web, path):
    r = web.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "<title>RouteWise</title>" in r.text
    assert r.headers["permissions-policy"] == LOCATION_FOR_OWN_ORIGIN
    for name, value in SECURITY_HEADERS.items():
        assert r.headers[name] == value, name


@pytest.mark.parametrize("path", ["/assets/app.js", "/api/health", "/api/not-a-route"])
def test_assets_and_api_responses_carry_the_same_policy(web, path):
    assert web.get(path).headers["permissions-policy"] == LOCATION_FOR_OWN_ORIGIN
