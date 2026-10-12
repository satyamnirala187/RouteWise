"""Google Maps link parsing and safe short-link resolution with manual-pin fallback.

Full Google Maps URLs are parsed offline and never fetched. Only allowlisted short-link
hosts are contacted, through `netsafe.head_redirect` (validated IP is the connection
target, HTTPS identity verified, headers only). A destination needs an explicit pin; a
map camera centre or address text needs manual correction (no geocoding).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from . import netsafe

SHORT_LINK_HOSTS = {"maps.app.goo.gl", "goo.gl"}
MAX_REDIRECTS = 4
LINK_BUDGET_S = 10.0  # whole short-link chain for one location edit
_GOOGLE_MAPS_HOST = re.compile(r"^(www\.|maps\.)?google\.(com|co\.in|[a-z]{2}|com\.[a-z]{2}|co\.[a-z]{2})$")
_NUM = r"(-?\d{1,3}(?:\.\d+)?)"
_PIN = re.compile(r"!3d" + _NUM + r"!4d" + _NUM)
_CAMERA = re.compile(r"/@" + _NUM + "," + _NUM + ",")
_PAIR = re.compile(r"^\s*" + _NUM + r"\s*,\s*" + _NUM + r"\s*$")


@dataclass(frozen=True)
class LocationResult:
    state: str  # resolved | needs_correction
    lat: float | None = None
    lng: float | None = None
    source: str | None = None  # place_pin | query | geo_uri | short_link | manual_pin
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.state == "resolved"


def _needs(note: str) -> LocationResult:
    return LocationResult("needs_correction", note=note)


def coordinates(lat: float | str, lng: float | str, source: str) -> LocationResult:
    try:
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return _needs("coordinates are not numbers")
    if not (-90 <= la <= 90 and -180 <= ln <= 180):
        return _needs("coordinates out of range")
    if la == 0 and ln == 0:
        return _needs("0,0 is not a delivery location")
    return LocationResult("resolved", round(la, 7), round(ln, 7), source)


def manual_pin(lat: float, lng: float) -> LocationResult:
    return coordinates(lat, lng, "manual_pin")


def parse_map_url(url: str) -> LocationResult:
    """Offline parse. Returns resolved, or needs_correction with a reason. Never fetches."""
    url = (url or "").strip()
    if not url:
        return _needs("no location given")
    if url.lower().startswith("geo:"):
        m = re.match(r"^geo:" + _NUM + "," + _NUM, url, re.I)
        return coordinates(*m.groups(), "geo_uri") if m else _needs("unreadable geo: link")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:  # malformed authority, e.g. "https://[broken/maps"
        return _needs("malformed link; choose a pin manually")
    if parts.scheme not in ("http", "https"):
        return _needs("not a Google Maps link")
    if parts.username or parts.password or port not in (None, 80, 443):
        return _needs("not a Google Maps link")
    host = (parts.hostname or "").lower()
    if host in SHORT_LINK_HOSTS:
        return _needs("short link must be resolved online")
    if not _GOOGLE_MAPS_HOST.match(host) or not (parts.path.startswith("/maps") or host.startswith("maps.")):
        return _needs("not a Google Maps link")
    path, query = unquote(parts.path), unquote(parts.query)
    pin = _PIN.search(path) or _PIN.search(query)
    if pin:
        return coordinates(*pin.groups(), "place_pin")
    q = parse_qs(parts.query)
    for key in ("destination", "query", "q", "daddr"):
        if key in q:
            m = _PAIR.match(q[key][0])
            if m:
                return coordinates(*m.groups(), "query")
            return _needs("address text only; choose a pin manually")
    if _CAMERA.search(path) or "ll" in q:
        return _needs("map view centre only, not a destination pin; choose a pin manually")
    return _needs("no destination found in link")


def resolve_link(
    url: str,
    *,
    allow_network: bool,
    head: Callable[[str], netsafe.HeadResult] | None = None,
    offline_reason: str = "link checks disabled",
    deadline: float | None = None,
) -> LocationResult:
    """Parse offline; follow allowlisted short links safely when allowed.

    `deadline` (time.monotonic()) bounds the whole chain: DNS, connects, reads and
    redirects. Defaults to LINK_BUDGET_S from now.
    """
    first = parse_map_url(url)
    if first.note != "short link must be resolved online":
        return first
    if not allow_network:
        return _needs(f"short link not checked ({offline_reason}); choose a pin manually")
    deadline = time.monotonic() + LINK_BUDGET_S if deadline is None else deadline
    head = head or (lambda u: netsafe.head_redirect(u, SHORT_LINK_HOSTS, deadline=deadline))
    current = url.strip()
    for _ in range(MAX_REDIRECTS):
        if time.monotonic() >= deadline:
            return _needs("link check time limit reached; choose a pin manually")
        try:
            result = head(current)
        except netsafe.UnsafeDestination:
            return _needs("short link points to a disallowed destination; choose a pin manually")
        except netsafe.FetchFailed:
            return _needs("short link could not be checked; choose a pin manually")
        if not result.location:
            return _needs("short link is broken or expired; choose a pin manually")
        try:
            current = urljoin(current, result.location)
            nxt = urlsplit(current)
            host = (nxt.hostname or "").lower()
        except ValueError:  # malformed Location header
            return _needs("short link redirected to a malformed address; choose a pin manually")
        if host in SHORT_LINK_HOSTS:
            if nxt.scheme != "https":
                return _needs("short link redirected insecurely; choose a pin manually")
            continue  # validated again (scheme, port, host, DNS) on the next hop
        parsed = parse_map_url(current)  # final Google Maps page is parsed, never fetched
        if parsed.resolved:
            return LocationResult("resolved", parsed.lat, parsed.lng, "short_link")
        if parsed.note == "not a Google Maps link":
            return _needs("short link redirected outside Google Maps; choose a pin manually")
        return parsed
    return _needs("too many redirects; choose a pin manually")
