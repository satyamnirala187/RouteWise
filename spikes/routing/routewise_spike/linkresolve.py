"""Guarded Google Maps link resolution with manual-pin fallback (R05, R24).

Rules:
- Full Google Maps URLs are parsed offline; they are never fetched.
- Only allowlisted short-link hosts are contacted, over HTTPS on the default
  port, reading the redirect Location header only (no body), with a redirect
  cap and timeout. Every hop's DNS answers must be public addresses.
- A destination needs an explicit pin (!3d/!4d, q=lat,lng, geo:). A camera
  centre (@lat,lng,zoom or ll=) is ambiguous and needs manual correction.
- Address text is not geocoded here; it needs manual correction.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

SHORT_LINK_HOSTS = {"maps.app.goo.gl", "goo.gl"}
_GOOGLE_MAPS_HOST = re.compile(r"^(www\.|maps\.)?google\.(com|co\.in|[a-z]{2}|com\.[a-z]{2}|co\.[a-z]{2})$")
_COORD = r"(-?\d{1,2}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)"
_PIN = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_CAMERA = re.compile(r"/@" + _COORD.replace(r",\s*", ",") + r",")
_PAIR = re.compile(r"^\s*" + _COORD + r"\s*$")


@dataclass(frozen=True)
class LinkResult:
    state: str  # resolved | needs_correction | rejected
    lat: float | None = None
    lng: float | None = None
    source: str = ""
    reason: str = ""


def _coords(lat: str | float, lng: str | float, source: str) -> LinkResult:
    la, ln = float(lat), float(lng)
    if not (-90 <= la <= 90 and -180 <= ln <= 180) or (la == 0 and ln == 0):
        return LinkResult("needs_correction", reason="coordinates out of range or null island")
    return LinkResult("resolved", la, ln, source=source)


def manual_pin(lat: float, lng: float) -> LinkResult:
    """Admin-selected pin: the safe fallback for anything unresolved."""
    return _coords(lat, lng, "manual_pin")


def _host_ok_shape(parts) -> str | None:
    if parts.username or parts.password:
        return "credentials in URL"
    if parts.port not in (None, 443):
        return "non-default port"
    host = parts.hostname or ""
    try:
        ipaddress.ip_address(host)
        return "IP-literal host"
    except ValueError:
        return None


def parse_map_url(url: str) -> LinkResult:
    url = url.strip()
    if url.lower().startswith("geo:"):
        m = re.match(r"^geo:" + _COORD, url, re.I)
        return _coords(*m.groups(), "geo_uri") if m else LinkResult("needs_correction", reason="unparseable geo URI")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return LinkResult("rejected", reason="unsupported scheme")
    bad = _host_ok_shape(parts)
    if bad:
        return LinkResult("rejected", reason=bad)
    host = (parts.hostname or "").lower()
    if host in SHORT_LINK_HOSTS:
        return LinkResult("needs_correction", reason="short link must be resolved online")
    if not _GOOGLE_MAPS_HOST.match(host) or not (parts.path.startswith("/maps") or host.startswith("maps.")):
        return LinkResult("rejected", reason="not a supported Google Maps link; not fetched")

    path = unquote(parts.path)
    pin = _PIN.search(path) or _PIN.search(unquote(parts.query))
    if pin:
        return _coords(*pin.groups(), "place_pin")
    q = parse_qs(parts.query)
    for key in ("destination", "query", "q", "daddr"):
        if key in q:
            m = _PAIR.match(q[key][0])
            if m:
                return _coords(*m.groups(), f"query:{key}")
            return LinkResult("needs_correction", reason="address text only; choose a pin manually")
    if _CAMERA.search(path) or "ll" in q:
        return LinkResult("needs_correction", reason="map camera centre only; not a destination pin")
    return LinkResult("needs_correction", reason="no destination found in link")


def _is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    return ip.is_global and not ip.is_multicast


def default_dns(host: str) -> list[str]:
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})


def default_fetch_location(url: str) -> str | None:  # pragma: no cover - network
    import httpx

    with httpx.Client(follow_redirects=False, timeout=5.0) as c:
        r = c.get(url, headers={"User-Agent": "RouteWise-link-check/0.1"})
        return r.headers.get("location") if r.is_redirect else None


def resolve_link(
    url: str,
    *,
    fetch_location: Callable[[str], str | None] = default_fetch_location,
    dns_lookup: Callable[[str], list[str]] = default_dns,
    max_redirects: int = 3,
) -> LinkResult:
    first = parse_map_url(url)
    if first.state != "needs_correction" or first.reason != "short link must be resolved online":
        return first
    current = url.strip()
    for _ in range(max_redirects):
        parts = urlsplit(current)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or host not in SHORT_LINK_HOSTS or _host_ok_shape(parts):
            return LinkResult("rejected", reason="redirect left the HTTPS short-link allowlist")
        try:
            addrs = dns_lookup(host)
        except OSError:
            return LinkResult("needs_correction", reason="short link host did not resolve; choose a pin manually")
        if not addrs or not all(_is_public(a) for a in addrs):
            return LinkResult("rejected", reason="short link host resolves to a private or reserved address")
        try:
            location = fetch_location(current)
        except Exception:
            return LinkResult("needs_correction", reason="short link could not be followed; choose a pin manually")
        if not location:
            return LinkResult("needs_correction", reason="short link is broken or expired; choose a pin manually")
        current = urljoin(current, location)
        nxt = urlsplit(current)
        if (nxt.hostname or "").lower() not in SHORT_LINK_HOSTS:
            result = parse_map_url(current)  # parsed offline, never fetched
            if result.state == "resolved":
                return LinkResult("resolved", result.lat, result.lng, source=f"short_link->{result.source}")
            return result
    return LinkResult("rejected", reason="too many redirects")
