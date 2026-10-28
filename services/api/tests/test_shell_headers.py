"""Step 5A-1: the offline app shell is served with the right revalidation, and nothing about the API or the security headers changes.

The service worker, the HTML and the manifest keep fixed names, so the browser must revalidate them (otherwise a new build or a
new worker is never noticed); only the content-hashed /assets/* are immutable; the API stays no-store. A temporary build is
served, so these tests do not depend on `npm run build`."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from routewise_api.main import SECURITY_HEADERS, create_app

IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def web(settings, clock, tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "icons").mkdir()
    (tmp_path / "assets" / "index-abc12345.js").write_text("//")
    (tmp_path / "index.html").write_text("<!doctype html><title>RouteWise</title>")
    (tmp_path / "sw.js").write_text("self.addEventListener('fetch', () => {});")
    (tmp_path / "manifest.webmanifest").write_text('{"name":"RouteWise"}')
    (tmp_path / "icons" / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("routewise_api.main.WEB_DIST", tmp_path)
    app = create_app(settings, clock=clock)
    yield TestClient(app)
    app.state.planning.shutdown()
    app.state.engine.dispose()


def assert_security_headers(r):
    for name, value in SECURITY_HEADERS.items():
        assert r.headers[name] == value, name
    assert r.headers["permissions-policy"] == "geolocation=(self), camera=(), microphone=()"


def test_the_worker_is_javascript_at_the_root_and_always_revalidated(web):
    r = web.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "html" not in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-cache"
    assert_security_headers(r)


@pytest.mark.parametrize("path", ["/", "/index.html", "/login", "/rider", "/rider/rounds/0b6c1c2e", "/admin/plan", "/no/such/deep/link"])
def test_the_html_document_is_always_revalidated_and_keeps_every_security_header(web, path):
    r = web.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"
    assert_security_headers(r)


def test_the_manifest_has_its_own_type_and_is_revalidated(web):
    r = web.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    assert r.headers["cache-control"] == "no-cache"
    assert_security_headers(r)


def test_icons_have_fixed_names_so_they_are_revalidated_not_immutable(web):
    r = web.get("/icons/icon-192.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-cache"


def test_only_content_hashed_assets_are_immutable_and_a_missing_asset_is_not_cached(web):
    ok = web.get("/assets/index-abc12345.js")
    assert ok.status_code == 200 and ok.headers["cache-control"] == IMMUTABLE
    assert_security_headers(ok)
    missing = web.get("/assets/index-zzzzzzzz.js")
    assert missing.status_code == 404 and "immutable" not in missing.headers.get("cache-control", "")


@pytest.mark.parametrize("path", ["/api/health", "/api/auth/session", "/api/not-a-route", "/api/admin/rounds"])
def test_api_responses_stay_no_store_even_when_they_are_errors(web, path):
    r = web.get(path)
    assert r.headers["cache-control"] == "no-store"
    assert_security_headers(r)


def test_an_authenticated_api_response_stays_no_store(admin):
    assert admin.get("/api/admin/rounds").headers["cache-control"] == "no-store"
