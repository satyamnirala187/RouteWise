"""Map-link parsing and hardened short-link resolution. All network I/O is mocked."""

import socket
import ssl

import pytest

from routewise_api import netsafe
from routewise_api.locations import SHORT_LINK_HOSTS, manual_pin, parse_map_url, resolve_link

PUBLIC_IP = "142.250.183.110"


# ------------------------------------------------------------------ offline parsing


@pytest.mark.parametrize("url, lat, lng, source", [
    ("https://www.google.com/maps/place/X/@28.60,77.10,15z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d28.6862643!4d77.20773",
     28.6862643, 77.20773, "place_pin"),
    ("https://www.google.com/maps/search/?api=1&query=28.6912,77.2091", 28.6912, 77.2091, "query"),
    ("https://www.google.com/maps/dir/?api=1&destination=28.6912%2C77.2091", 28.6912, 77.2091, "query"),
    ("https://maps.google.com/?q=28.6912,77.2091", 28.6912, 77.2091, "query"),
    ("https://www.google.co.in/maps?q=28.6912,77.2091", 28.6912, 77.2091, "query"),
    ("geo:28.6912,77.2091", 28.6912, 77.2091, "geo_uri"),
])
def test_supported_formats_resolve_to_the_destination(url, lat, lng, source):
    r = parse_map_url(url)
    assert (r.state, r.lat, r.lng, r.source) == ("resolved", lat, lng, source)


@pytest.mark.parametrize("url, fragment", [
    ("https://www.google.com/maps/@28.68,77.20,17z", "map view centre"),
    ("https://maps.google.com/?ll=28.68,77.20&z=15", "map view centre"),
    ("https://www.google.com/maps/search/?api=1&query=Hansraj+College", "address text"),
    ("https://www.google.com/maps?q=0,0", "0,0"),
    ("https://www.google.com/maps?q=95.1,77.1", "out of range"),
    ("https://evil.example/maps?q=28.6,77.2", "not a Google Maps link"),
    ("https://www.google.com:8443/maps?q=28.6,77.2", "not a Google Maps link"),
    ("https://user:pw@www.google.com/maps?q=28.6,77.2", "not a Google Maps link"),
    ("javascript:alert(1)", "not a Google Maps link"),
    ("", "no location"),
])
def test_ambiguous_or_unsupported_links_need_a_manual_pin(url, fragment):
    r = parse_map_url(url)
    assert r.state == "needs_correction" and fragment in r.note and r.lat is None


def test_manual_pin_validation():
    assert manual_pin(28.6883, 77.2148).resolved
    assert not manual_pin(0, 0).resolved and not manual_pin(91, 0).resolved
    assert manual_pin(28.6883, 77.2148).source == "manual_pin"


# ------------------------------------------------------------------ URL and address validation


@pytest.mark.parametrize("url", [
    "http://maps.app.goo.gl/x",              # downgrade
    "https://maps.app.goo.gl:8443/x",        # port
    "https://user@maps.app.goo.gl/x",        # userinfo
    "https://142.250.183.110/x",             # IP literal
    "https://evil.example/x",                # not allowlisted
    "https://maps.app.goo.gl.evil.example/x",
    "ftp://maps.app.goo.gl/x",
    "https://maps.app.goo.gl/a b",           # header injection via target
    "https://maps.app.goo.gl/x\r\nHost: evil",
])
def test_unsafe_urls_are_refused_before_dns(url):
    calls = []
    with pytest.raises(netsafe.UnsafeDestination):
        netsafe.head_redirect(url, SHORT_LINK_HOSTS, resolver=lambda h: calls.append(h) or [PUBLIC_IP],
                              connector=lambda *a: pytest.fail("connected"))
    assert calls == []


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
    "224.0.0.1", "::1", "fe80::1", "fd00::1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "240.0.0.1",
])
def test_non_public_addresses_are_refused(addr):
    assert not netsafe.is_public_ip(addr)
    with pytest.raises(netsafe.UnsafeDestination):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS, resolver=lambda h: [addr],
                              connector=lambda *a: pytest.fail("connected to a private address"))


def test_any_private_address_in_the_answer_set_refuses_the_host():
    with pytest.raises(netsafe.UnsafeDestination):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS,
                              resolver=lambda h: [PUBLIC_IP, "10.0.0.5"], connector=lambda *a: pytest.fail("connected"))


# ------------------------------------------------------------------ pinned connection


class FakeTLS:
    def __init__(self, payload: bytes, chunk: int = 4096):
        self.payload, self.chunk, self.sent, self.closed = payload, chunk, b"", False

    def settimeout(self, t):
        self.timeout = t

    def sendall(self, data):
        self.sent += data

    def recv(self, n):
        out, self.payload = self.payload[: min(n, self.chunk)], self.payload[min(n, self.chunk):]
        return out

    def close(self):
        self.closed = True


def fake_connector(payload: bytes, seen: list):
    def connect(ip, hostname, timeout):
        sock = FakeTLS(payload)
        seen.append((ip, hostname, timeout, sock))
        return sock
    return connect


REDIRECT = (b"HTTP/1.1 302 Found\r\nLocation: https://www.google.com/maps/place/X/data=!3d28.6862643!4d77.20773\r\n"
            b"Content-Length: 999999999\r\n\r\nBODY-SHOULD-NOT-BE-READ")


def test_connection_target_is_the_validated_ip_and_hostname_is_kept_for_tls():
    seen = []
    r = netsafe.head_redirect("https://maps.app.goo.gl/AbC?g_st=x", SHORT_LINK_HOSTS,
                              resolver=lambda h: [PUBLIC_IP], connector=fake_connector(REDIRECT, seen))
    ip, hostname, timeout, sock = seen[0]
    assert ip == PUBLIC_IP == r.connected_ip and hostname == "maps.app.goo.gl" and timeout == netsafe.CONNECT_TIMEOUT_S
    assert sock.sent.startswith(b"GET /AbC?g_st=x HTTP/1.1\r\nHost: maps.app.goo.gl\r\n") and sock.closed
    assert r.status == 302 and r.location.startswith("https://www.google.com/maps/place/")


def test_dns_rebinding_cannot_swap_the_target_between_check_and_connect():
    answers = iter([[PUBLIC_IP], ["127.0.0.1"]])  # a rebinding resolver flips after the first lookup
    seen = []
    netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS,
                          resolver=lambda h: next(answers), connector=fake_connector(REDIRECT, seen))
    assert [s[0] for s in seen] == [PUBLIC_IP]  # one lookup, and the socket went to the IP that was checked


def test_tls_connect_uses_ip_for_socket_and_hostname_for_sni_and_cert(monkeypatch):
    captured = {}

    class FakeRaw:
        def close(self):
            captured["raw_closed"] = True

    def fake_create_connection(addr, timeout):
        captured["addr"], captured["timeout"] = addr, timeout
        return FakeRaw()

    def fake_wrap(self, sock, server_hostname=None, **kw):
        captured.update(server_hostname=server_hostname, verify=self.verify_mode, check=self.check_hostname,
                        min_version=self.minimum_version)
        return "tls-socket"

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", fake_wrap)
    assert netsafe.tls_connect(PUBLIC_IP, "maps.app.goo.gl", 5.0) == "tls-socket"
    assert captured["addr"] == (PUBLIC_IP, 443) and captured["server_hostname"] == "maps.app.goo.gl"
    assert captured["verify"] == ssl.CERT_REQUIRED and captured["check"] is True
    assert captured["min_version"] >= ssl.TLSVersion.TLSv1_2


def test_tls_failure_closes_raw_socket(monkeypatch):
    closed = []

    class FakeRaw:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: FakeRaw())

    def bad_wrap(self, sock, server_hostname=None, **kw):
        raise ssl.SSLCertVerificationError("hostname mismatch")

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", bad_wrap)
    with pytest.raises(ssl.SSLError):
        netsafe.tls_connect(PUBLIC_IP, "maps.app.goo.gl", 5.0)
    assert closed == [True]


def test_certificate_errors_and_timeouts_become_fetch_failures():
    def raise_(exc):
        def f(*a):
            raise exc
        return f
    for exc in (ssl.SSLCertVerificationError("bad cert"), socket.timeout("slow"), ConnectionRefusedError()):
        with pytest.raises(netsafe.FetchFailed):
            netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS,
                                  resolver=lambda h: [PUBLIC_IP], connector=raise_(exc))


def test_response_headers_are_bounded_and_body_is_never_read():
    endless = b"HTTP/1.1 302 Found\r\n" + b"X-Pad: " + b"a" * (netsafe.MAX_HEADER_BYTES + 100)
    with pytest.raises(netsafe.FetchFailed, match="too large"):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS,
                              resolver=lambda h: [PUBLIC_IP], connector=fake_connector(endless, []))
    big_body = REDIRECT + b"x" * (1024 * 1024)  # 1 MB body after the headers
    sock = FakeTLS(big_body, chunk=64)
    r = netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS,
                              resolver=lambda h: [PUBLIC_IP], connector=lambda *a: sock)
    assert r.location and len(sock.payload) > 1024 * 1024 - 64  # reading stopped once the headers ended


def test_malformed_or_incomplete_responses_fail_safely():
    for payload in (b"", b"garbage\r\n\r\n", b"HTTP/1.1 302 Found\r\nLocation: x"):
        with pytest.raises(netsafe.FetchFailed):
            netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS,
                                  resolver=lambda h: [PUBLIC_IP], connector=fake_connector(payload, []))


def test_hop_deadline_is_enforced():
    times = iter([0.0, 0.0, 100.0, 100.0])
    slow = FakeTLS(b"HTTP/1.1 302 Found\r\n", chunk=4)  # trickles bytes, never finishes headers
    with pytest.raises(netsafe.FetchFailed):
        netsafe.head_redirect("https://maps.app.goo.gl/x", SHORT_LINK_HOSTS, resolver=lambda h: [PUBLIC_IP],
                              connector=lambda *a: slow, clock=lambda: next(times, 100.0))


# ------------------------------------------------------------------ redirect chain


def hop(location=None, status=302):
    return netsafe.HeadResult(status=status, location=location, connected_ip=PUBLIC_IP)


def test_short_link_resolves_via_parsed_final_url_without_fetching_it():
    fetched = []

    def head(url):
        fetched.append(url)
        return hop("https://www.google.com/maps/place/X/data=!3d28.6862643!4d77.20773")

    r = resolve_link("https://maps.app.goo.gl/AbC", allow_network=True, head=head)
    assert r.resolved and r.source == "short_link" and (r.lat, r.lng) == (28.6862643, 77.20773)
    assert fetched == ["https://maps.app.goo.gl/AbC"]


def test_every_redirect_hop_is_validated_again():
    hops = iter([hop("https://goo.gl/maps/next"), hop("https://www.google.com/maps?q=28.69,77.21")])
    fetched = []
    r = resolve_link("https://maps.app.goo.gl/a", allow_network=True,
                     head=lambda u: fetched.append(u) or next(hops))
    assert r.resolved and fetched == ["https://maps.app.goo.gl/a", "https://goo.gl/maps/next"]


@pytest.mark.parametrize("location, fragment", [
    ("http://maps.app.goo.gl/b", "insecurely"),
    ("https://169.254.169.254/latest/meta-data", "outside Google Maps"),
    ("https://evil.example/maps?q=1,2", "outside Google Maps"),
    ("https://www.google.com/maps/@28.68,77.20,17z", "map view centre"),
])
def test_unsafe_or_ambiguous_redirect_destinations_need_manual_pin(location, fragment):
    r = resolve_link("https://maps.app.goo.gl/a", allow_network=True, head=lambda u: hop(location))
    assert r.state == "needs_correction" and fragment in r.note


def test_redirect_loops_and_dead_links_fall_back_to_manual_pin():
    loop = resolve_link("https://maps.app.goo.gl/a", allow_network=True, head=lambda u: hop("https://maps.app.goo.gl/a"))
    assert "too many redirects" in loop.note
    dead = resolve_link("https://maps.app.goo.gl/a", allow_network=True, head=lambda u: hop(None, 404))
    assert "broken or expired" in dead.note


def test_unsafe_destination_and_fetch_failure_map_to_clear_notes():
    def unsafe(u):
        raise netsafe.UnsafeDestination("non-public")

    def failed(u):
        raise netsafe.FetchFailed("timeout")

    assert "disallowed destination" in resolve_link("https://maps.app.goo.gl/a", allow_network=True, head=unsafe).note
    assert "could not be checked" in resolve_link("https://maps.app.goo.gl/a", allow_network=True, head=failed).note
    off = resolve_link("https://maps.app.goo.gl/a", allow_network=False)
    assert off.state == "needs_correction" and "not checked" in off.note
