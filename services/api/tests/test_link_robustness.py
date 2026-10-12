"""Malformed/Unicode links never crash an import or a location edit; slow DNS or short-link
resolution stays inside documented budgets and never blocks the event loop. Network is mocked."""

import threading
import time
from dataclasses import replace

import pytest

from routewise_api import locations, netsafe
from routewise_api.locations import SHORT_LINK_HOSTS, parse_map_url, resolve_link

from .conftest import HEADER, PIN, upload, xlsx

PUBLIC_IP = "142.250.183.110"
BAD_LINKS = [
    "https://[broken/maps",
    "http://[::1/x",
    "https://www.google.com:99999/maps?q=28.6,77.2",
    "https://maps.app.goo.gl/हिन्दी",
    "https://maps.app.goo.gl/%E0%A4",
    "https://www.google.com/maps/place/हिन्दी/@28.6,77.1,15z/data=!3d28.6862643!4d77.20773",
]


class FakeSock:
    def __init__(self, payload: bytes):
        self.payload, self.sent = payload, b""

    def settimeout(self, t):
        pass

    def sendall(self, data):
        self.sent += data

    def recv(self, n):
        out, self.payload = self.payload[:n], self.payload[n:]
        return out

    def close(self):
        pass


# ------------------------------------------------------------------ parsing and the client


@pytest.mark.parametrize("url", BAD_LINKS)
def test_malformed_and_unicode_links_parse_without_raising(url):
    r = parse_map_url(url)
    assert r.state in ("resolved", "needs_correction")


def test_unicode_place_names_in_full_links_still_resolve():
    r = parse_map_url(BAD_LINKS[-1])
    assert r.resolved and (r.lat, r.lng) == (28.6862643, 77.20773)


def test_unicode_short_link_is_utf8_percent_encoded_and_still_pinned_to_validated_ip():
    seen = []

    def connector(ip, host, timeout):
        seen.append((ip, host))
        seen.append(sock := FakeSock(b"HTTP/1.1 302 Found\r\nLocation: https://www.google.com/maps?q=28.69,77.21\r\n\r\n"))
        return sock

    r = netsafe.head_redirect("https://maps.app.goo.gl/हिन्दी?x=दिल्ली", SHORT_LINK_HOSTS,
                              resolver=lambda h: [PUBLIC_IP], connector=connector)
    assert seen[0] == (PUBLIC_IP, "maps.app.goo.gl") and r.status == 302
    assert seen[1].sent.startswith(
        b"GET /%E0%A4%B9%E0%A4%BF%E0%A4%A8%E0%A5%8D%E0%A4%A6%E0%A5%80?x=%E0%A4%A6%E0%A4%BF%E0%A4%B2%E0%A5%8D%E0%A4%B2%E0%A5%80 HTTP/1.1\r\n")


@pytest.mark.parametrize("url", ["https://[broken/maps", "https://maps.app.goo.gl:99999/x", "https://maps.app.goo.gl/a\tb",
                                 "https://maps.app.goo.gl/a\x00b", "https://maps.app.gооgle.com/x",  # Cyrillic 'о'
                                 "https://maps.app.goo.gl/" + "a" * 3000])
def test_malformed_targets_are_refused_before_any_network(url):
    with pytest.raises(netsafe.UnsafeDestination):
        netsafe.head_redirect(url, SHORT_LINK_HOSTS, resolver=lambda h: pytest.fail("resolved"),
                              connector=lambda *a: pytest.fail("connected"))


@pytest.mark.parametrize("location", ["https://[x/maps", "https://maps.app.goo.gl:abc/x", "http://[::1"])
def test_malformed_redirect_locations_fall_back_to_manual_pin(location):
    r = resolve_link("https://maps.app.goo.gl/a", allow_network=True,
                     head=lambda u: netsafe.HeadResult(302, location, PUBLIC_IP))
    assert r.state == "needs_correction" and "choose a pin manually" in r.note


@pytest.mark.parametrize("status_line", [b"HTTP/1.1 \xb2\xb2\xb2 Odd", b"HTTP/1.1 3O2 Found", b"HTTP/2 302", b"HTTP/1.1 30"])
def test_non_ascii_or_malformed_status_lines_fail_safely(status_line):
    with pytest.raises(netsafe.FetchFailed, match="status line"):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS, resolver=lambda h: [PUBLIC_IP],
                              connector=lambda *a: FakeSock(status_line + b"\r\nLocation: x\r\n\r\n"))


# ------------------------------------------------------------------ requests never crash


@pytest.fixture
def network_mocks(monkeypatch):
    """Short-link checks enabled, with DNS/TLS mocked: every short link redirects to a pin."""
    monkeypatch.setattr(netsafe, "system_resolver", lambda host: [PUBLIC_IP])
    monkeypatch.setattr(netsafe, "tls_connect", lambda ip, host, timeout: FakeSock(
        b"HTTP/1.1 302 Found\r\nLocation: https://www.google.com/maps?q=28.6912,77.2091\r\n\r\n"))


def enable_links(app, **kw):
    app.state.settings = replace(app.state.settings, resolve_short_links=True, **kw)


def test_bad_links_cannot_crash_an_excel_import(app, admin, network_mocks):
    enable_links(app)
    rows = [HEADER] + [[f"Test Customer L{i}", "Box", f"0000000{i:04d}", link, None] for i, link in enumerate(BAD_LINKS)]
    rows.append(["Test Customer OK", "Box", "00000009999", PIN, None])
    r = upload(admin, xlsx(rows))
    assert r.status_code == 201
    p = r.json()
    assert p["summary"]["can_commit"] and p["summary"]["total_rows"] == len(BAD_LINKS) + 1
    states = {row["values"]["location"]: row["location"]["state"] for row in p["rows"]}
    assert states["https://[broken/maps"] == "needs_correction"
    assert states["https://maps.app.goo.gl/हिन्दी"] == "resolved"  # encoded, fetched via mock, pin parsed
    assert states[PIN] == "resolved"
    assert admin.send("POST", f"/api/admin/imports/{p['id']}/commit").status_code == 200


@pytest.mark.parametrize("link", BAD_LINKS)
def test_bad_links_cannot_crash_a_location_edit(app, admin, network_mocks, link):
    enable_links(app)
    p = upload(admin, xlsx([HEADER, ["Test Customer E", "Box", "00000000001", PIN, None]])).json()
    rid = admin.send("POST", f"/api/admin/imports/{p['id']}/commit").json()["round_id"]
    order = admin.get(f"/api/admin/rounds/{rid}/orders").json()[0]
    r = admin.send("POST", f"/api/admin/orders/{order['id']}/location-link", json={"version": order["version"], "link": link})
    assert r.status_code == 200
    assert r.json()["location"]["state"] in ("resolved", "needs_correction")


# ------------------------------------------------------------------ time budgets


def test_slow_dns_is_cut_off_by_the_overall_deadline():
    started = time.monotonic()
    with pytest.raises(netsafe.FetchFailed, match="DNS lookup timed out"):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS,
                              resolver=lambda h: time.sleep(2) or [PUBLIC_IP],
                              connector=lambda *a: pytest.fail("connected"), deadline=time.monotonic() + 0.3)
    assert time.monotonic() - started < 1.0


def test_dns_has_its_own_timeout_even_without_a_caller_deadline(monkeypatch):
    monkeypatch.setattr(netsafe, "DNS_TIMEOUT_S", 0.2)
    started = time.monotonic()
    with pytest.raises(netsafe.FetchFailed, match="DNS lookup timed out"):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS, resolver=lambda h: time.sleep(1) or [PUBLIC_IP])
    assert time.monotonic() - started < 0.8


def test_expired_budget_fails_before_connecting():
    with pytest.raises(netsafe.FetchFailed, match="budget"):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS, resolver=lambda h: [PUBLIC_IP],
                              connector=lambda *a: pytest.fail("connected"), deadline=time.monotonic() - 1)


def test_redirect_chain_shares_one_deadline():
    def slow_hop(url):
        time.sleep(0.15)
        return netsafe.HeadResult(302, "https://goo.gl/maps/next", PUBLIC_IP)

    started = time.monotonic()
    r = resolve_link("https://maps.app.goo.gl/a", allow_network=True, head=slow_hop, deadline=time.monotonic() + 0.25)
    assert r.state == "needs_correction" and "time limit" in r.note
    assert time.monotonic() - started < 0.6


def test_import_link_budget_is_total_and_includes_dns(app, admin, monkeypatch):
    monkeypatch.setattr(netsafe, "system_resolver", lambda host: time.sleep(1.5) or [PUBLIC_IP])
    enable_links(app, import_link_budget_s=1.0)
    rows = [HEADER] + [[f"Test Customer S{i}", "Box", f"0000000{i:04d}", f"https://maps.app.goo.gl/s{i}", None] for i in range(6)]
    started = time.monotonic()
    p = upload(admin, xlsx(rows)).json()
    elapsed = time.monotonic() - started
    assert elapsed < 2.5, elapsed  # 6 slow lookups would take 9 s without a shared budget
    assert all(r["location"]["state"] == "needs_correction" for r in p["rows"])
    notes = {r["location"]["note"] for r in p["rows"]}
    assert any("could not be checked" in n for n in notes) and any("limit reached" in n for n in notes)


def test_event_loop_stays_responsive_during_a_slow_import(app, monkeypatch):
    from fastapi.testclient import TestClient

    from .conftest import make_user

    monkeypatch.setattr(netsafe, "system_resolver", lambda host: time.sleep(1.0) or [PUBLIC_IP])
    enable_links(app, import_link_budget_s=2.0)
    make_user(app, "admin1", "admin")
    rows = [HEADER] + [[f"Test Customer R{i}", "Box", f"0000000{i:04d}", f"https://maps.app.goo.gl/r{i}", None] for i in range(4)]
    data = xlsx(rows)
    with TestClient(app) as c:  # ONE client = one event loop shared by both requests
        assert c.post("/api/auth/login", json={"username": "admin1", "password": "correct horse battery"},
                      headers={"Origin": "http://localhost:5173"}).status_code == 200
        csrf = c.get("/api/auth/session").json()["csrf_token"]
        done = {}

        def do_import():
            done["import"] = c.post("/api/admin/imports", headers={"Origin": "http://localhost:5173", "X-CSRF-Token": csrf},
                                    files={"file": ("o.xlsx", data, "application/octet-stream")})

        t = threading.Thread(target=do_import)
        t.start()
        time.sleep(0.3)  # the import is now waiting on slow DNS
        assert "import" not in done
        started = time.monotonic()
        health = c.get("/api/health")
        latency = time.monotonic() - started
        t.join(timeout=10)
    assert health.status_code == 200 and latency < 0.5, latency
    assert done["import"].status_code == 201


def test_concurrent_imports_are_bounded(app, admin, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(netsafe, "system_resolver", lambda host: gate.wait(5) and [PUBLIC_IP])
    enable_links(app, max_concurrent_imports=1, import_link_budget_s=5.0)
    data = xlsx([HEADER, ["Test Customer B", "Box", "00000000001", "https://maps.app.goo.gl/b", None]])
    first = {}
    t = threading.Thread(target=lambda: first.setdefault("r", upload(admin, data)))
    t.start()
    time.sleep(0.3)
    second = upload(admin, data)
    gate.set()
    t.join(timeout=10)
    assert second.status_code == 429 and "Another import" in second.json()["detail"]
    assert first["r"].status_code == 201
    assert upload(admin, xlsx([HEADER, ["Test Customer C", "Box", "00000000002", PIN, None]])).status_code == 201
