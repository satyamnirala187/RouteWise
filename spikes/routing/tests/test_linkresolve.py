"""Criterion 10: map link resolution, ambiguity, broken links, manual pin and SSRF guards."""

import pytest

from routewise_spike.linkresolve import manual_pin, parse_map_url, resolve_link

PUBLIC = lambda host: ["142.250.193.110"]  # noqa: E731 - a public address


@pytest.mark.parametrize(
    "url, lat, lng, source",
    [
        ("https://www.google.com/maps/place/Cubbon+Park/@12.9700,77.5800,15z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d12.9763!4d77.5929",
         12.9763, 77.5929, "place_pin"),
        ("https://www.google.com/maps/search/?api=1&query=12.9716,77.5960", 12.9716, 77.5960, "query:query"),
        ("https://www.google.com/maps/dir/?api=1&destination=12.9755%2C77.6066", 12.9755, 77.6066, "query:destination"),
        ("https://maps.google.com/?q=12.9822,77.6084", 12.9822, 77.6084, "query:q"),
        ("https://www.google.co.in/maps?q=12.9987,77.5921", 12.9987, 77.5921, "query:q"),
        ("geo:12.9346,77.6113", 12.9346, 77.6113, "geo_uri"),
    ],
)
def test_coordinate_urls_resolve_to_the_destination_pin(url, lat, lng, source):
    r = parse_map_url(url)
    assert (r.state, r.lat, r.lng, r.source) == ("resolved", lat, lng, source)


def test_place_pin_wins_over_camera_centre():
    r = parse_map_url("https://www.google.com/maps/place/X/@10.0,70.0,12z/data=!3d12.9763!4d77.5929")
    assert (r.lat, r.lng) == (12.9763, 77.5929)


@pytest.mark.parametrize(
    "url, reason_part",
    [
        ("https://www.google.com/maps/@12.9716,77.5960,17z", "camera centre"),
        ("https://maps.google.com/?ll=12.9716,77.5960&z=15", "camera centre"),
        ("https://www.google.com/maps/search/?api=1&query=UB+City+Bengaluru", "address text"),
        ("https://www.google.com/maps", "no destination"),
        ("https://www.google.com/maps?q=0,0", "null island"),
        ("https://www.google.com/maps?q=95.1,77.1", "out of range"),
    ],
)
def test_ambiguous_or_textual_links_need_manual_correction(url, reason_part):
    r = parse_map_url(url)
    assert r.state == "needs_correction" and reason_part in r.reason and r.lat is None


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/maps?q=12.9,77.5",
        "http://127.0.0.1/maps?q=12.9,77.5",
        "https://maps.app.goo.gl@169.254.169.254/x",
        "https://www.google.com:8443/maps?q=12.9,77.5",
        "file:///etc/passwd",
        "javascript:alert(1)",
    ],
)
def test_unsupported_hosts_and_schemes_are_rejected_without_fetching(url):
    called = []
    r = resolve_link(url, fetch_location=lambda u: called.append(u), dns_lookup=PUBLIC)
    assert r.state == "rejected" and called == []


def test_short_link_follows_only_location_headers_and_parses_offline():
    hops = {"https://maps.app.goo.gl/AbC123": "https://www.google.com/maps/place/X/data=!3d12.9763!4d77.5929"}
    fetched = []

    def fetch(u):
        fetched.append(u)
        return hops.get(u)

    r = resolve_link("https://maps.app.goo.gl/AbC123", fetch_location=fetch, dns_lookup=PUBLIC)
    assert r.state == "resolved" and (r.lat, r.lng) == (12.9763, 77.5929)
    assert r.source == "short_link->place_pin"
    assert fetched == ["https://maps.app.goo.gl/AbC123"]  # the google.com page itself is never fetched


def test_short_link_to_camera_only_still_needs_correction():
    r = resolve_link("https://maps.app.goo.gl/cam",
                     fetch_location=lambda u: "https://www.google.com/maps/@12.97,77.59,15z", dns_lookup=PUBLIC)
    assert r.state == "needs_correction"


@pytest.mark.parametrize(
    "addrs", [["127.0.0.1"], ["10.0.0.8"], ["169.254.169.254"], ["192.168.1.1"], ["::1"], ["142.250.1.1", "10.1.1.1"]]
)
def test_short_link_resolving_to_private_network_is_rejected_before_fetch(addrs):
    called = []
    r = resolve_link("https://maps.app.goo.gl/x", fetch_location=lambda u: called.append(u), dns_lookup=lambda h: addrs)
    assert r.state == "rejected" and "private" in r.reason and called == []


def test_unsafe_redirects_are_rejected():
    def to_internal(u):
        return "http://169.254.169.254/latest/meta-data"

    assert resolve_link("https://maps.app.goo.gl/x", fetch_location=to_internal, dns_lookup=PUBLIC).state == "rejected"
    loop = resolve_link("https://maps.app.goo.gl/x", fetch_location=lambda u: "https://maps.app.goo.gl/x",
                        dns_lookup=PUBLIC, max_redirects=3)
    assert loop.state == "rejected" and "too many redirects" in loop.reason
    downgrade = resolve_link("https://maps.app.goo.gl/x", fetch_location=lambda u: "http://maps.app.goo.gl/y",
                             dns_lookup=PUBLIC)
    assert downgrade.state == "rejected"


def test_broken_or_failing_short_links_ask_for_a_manual_pin():
    assert resolve_link("https://maps.app.goo.gl/gone", fetch_location=lambda u: None,
                        dns_lookup=PUBLIC).state == "needs_correction"

    def boom(u):
        raise TimeoutError("slow")

    assert resolve_link("https://maps.app.goo.gl/slow", fetch_location=boom, dns_lookup=PUBLIC).state == "needs_correction"

    def nxdomain(h):
        raise OSError("nxdomain")

    assert resolve_link("https://maps.app.goo.gl/x", fetch_location=boom, dns_lookup=nxdomain).state == "needs_correction"


def test_manual_pin_is_the_validated_fallback():
    assert manual_pin(12.9716, 77.596).state == "resolved"
    assert manual_pin(12.9716, 77.596).source == "manual_pin"
    assert manual_pin(0, 0).state == "needs_correction"
    assert manual_pin(91, 0).state == "needs_correction"
