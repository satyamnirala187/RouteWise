"""Minimal, pinned HTTPS client used only to read redirect headers of allowlisted short links.

Defences:
- Only `https`, default port 443, no userinfo, host in an explicit allowlist (ASCII).
- Malformed URLs (e.g. a broken IPv6 bracket) are rejected as UnsafeDestination, never raised.
- Non-ASCII path/query characters are percent-encoded as UTF-8 (IRI → URI); control
  characters and whitespace are rejected (no header injection).
- DNS is resolved ONCE per hop, on a small bounded thread pool with a timeout; every
  returned address must be public (not private, loopback, link-local, multicast, reserved,
  unspecified, CGNAT, IPv4-mapped private...).
- The socket connects to that validated IP itself (no second lookup), so DNS rebinding
  between validation and connection is impossible.
- TLS uses SNI = hostname and verifies the certificate chain and hostname (default
  context, CERT_REQUIRED, check_hostname=True), so pinning the IP keeps HTTPS identity checks.
- Only the status line and headers are read, capped in bytes; the body is never read.
- Budgets: DNS ≤ 3 s, connect (incl. TLS handshake) ≤ 5 s, read ≤ 5 s, ≤ 8 s per hop,
  and never beyond the caller's overall `deadline` (time.monotonic() value).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

MAX_HEADER_BYTES = 16 * 1024
DNS_TIMEOUT_S = 3.0
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 5.0
HOP_DEADLINE_S = 8.0
USER_AGENT = "RouteWise-link-check/1.0"
DNS_WORKERS = 4  # stuck system lookups can occupy at most this many threads
_STATUS_LINE = re.compile(r"^HTTP/1\.[01] ([0-9]{3})(?: |$)")  # ASCII digits only ("²".isdigit() is True)
_UNSAFE_TARGET_CHARS = re.compile(r"[\x00-\x20\x7f]")
_TARGET_SAFE = "/?&=:@!$'()*+,;%-._~"  # RFC 3986 reserved/unreserved kept; everything else UTF-8 %-encoded

_dns_pool = ThreadPoolExecutor(max_workers=DNS_WORKERS, thread_name_prefix="routewise-dns")


class UnsafeDestination(Exception):
    """The URL or its resolved addresses are not allowed."""


class FetchFailed(Exception):
    """Network/TLS/protocol failure or budget exhausted; caller falls back to a manual pin."""


def is_public_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast and not ip.is_reserved


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return list(dict.fromkeys(info[4][0] for info in infos))


def tls_connect(ip: str, hostname: str, timeout: float) -> ssl.SSLSocket:
    """Connect to the already-validated IP and verify the certificate for `hostname`.
    `timeout` bounds the TCP connect and the TLS handshake."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:  # explicit: asserts vanish under -O
        raise ssl.SSLError("TLS context does not verify certificates")
    raw = socket.create_connection((ip, 443), timeout=timeout)
    try:
        return ctx.wrap_socket(raw, server_hostname=hostname)
    except BaseException:
        raw.close()
        raise


@dataclass(frozen=True)
class HeadResult:
    status: int
    location: str | None
    connected_ip: str


def validate_url(url: str, allowed_hosts: set[str]) -> tuple[str, str]:
    """Returns (hostname, ASCII request target) or raises UnsafeDestination."""
    if _UNSAFE_TARGET_CHARS.search(url):  # checked on the raw URL: urlsplit silently strips \t \r \n
        raise UnsafeDestination("control characters or whitespace in URL")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:  # e.g. "https://[broken/maps": invalid IPv6 literal / port
        raise UnsafeDestination("malformed URL") from exc
    if parts.scheme != "https":
        raise UnsafeDestination("only https is allowed")
    if parts.username or parts.password:
        raise UnsafeDestination("credentials in URL")
    if port not in (None, 443):
        raise UnsafeDestination("non-default port")
    host = (parts.hostname or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeDestination("IP-literal host")
    if host not in allowed_hosts:  # allowlist is ASCII, so IDN/homograph hosts never match
        raise UnsafeDestination("host not allowlisted")
    raw_target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    if _UNSAFE_TARGET_CHARS.search(raw_target):
        raise UnsafeDestination("invalid request target")
    target = quote(raw_target, safe=_TARGET_SAFE)  # UTF-8 percent-encoding of non-ASCII
    if len(target) > 2048:
        raise UnsafeDestination("request target too long")
    return host, target


def _remaining(deadline: float, clock: Callable[[], float]) -> float:
    left = deadline - clock()
    if left <= 0:
        raise FetchFailed("time budget exhausted")
    return left


def head_redirect(
    url: str,
    allowed_hosts: set[str],
    *,
    resolver: Callable[[str], list[str]] | None = None,
    connector: Callable[[str, str, float], ssl.SSLSocket] | None = None,
    clock: Callable[[], float] = time.monotonic,
    deadline: float | None = None,
) -> HeadResult:
    host, target = validate_url(url, allowed_hosts)
    resolver = resolver or system_resolver  # looked up at call time (patchable in tests)
    connector = connector or tls_connect
    hop_deadline = clock() + HOP_DEADLINE_S
    deadline = hop_deadline if deadline is None else min(deadline, hop_deadline)

    future = _dns_pool.submit(resolver, host)
    try:
        addrs = future.result(timeout=min(DNS_TIMEOUT_S, _remaining(deadline, clock)))
    except FutureTimeout as exc:
        future.cancel()  # if still queued; a running system lookup finishes on its own bounded thread
        raise FetchFailed("DNS lookup timed out") from exc
    except OSError as exc:
        raise FetchFailed("DNS lookup failed") from exc
    if not addrs:
        raise FetchFailed("no addresses")
    if not all(is_public_ip(a) for a in addrs):
        raise UnsafeDestination("host resolves to a non-public address")
    ip = addrs[0]  # the validated address IS the connection target

    try:
        sock = connector(ip, host, min(CONNECT_TIMEOUT_S, _remaining(deadline, clock)))
    except (OSError, ssl.SSLError) as exc:  # socket.timeout and SSL errors are OSError subclasses
        raise FetchFailed(f"connection failed: {type(exc).__name__}") from exc
    try:
        request = (
            f"GET {target} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {USER_AGENT}\r\n"
            "Accept: */*\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
        )
        sock.settimeout(min(READ_TIMEOUT_S, _remaining(deadline, clock)))
        sock.sendall(request.encode("ascii"))  # target and host are ASCII by construction
        buf = b""
        while b"\r\n\r\n" not in buf:
            sock.settimeout(min(READ_TIMEOUT_S, _remaining(deadline, clock)))
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_HEADER_BYTES:
                raise FetchFailed("response headers too large")
    except (OSError, ssl.SSLError) as exc:
        raise FetchFailed(f"read failed: {type(exc).__name__}") from exc
    finally:
        sock.close()
    if b"\r\n\r\n" not in buf:
        raise FetchFailed("incomplete or empty response headers")
    lines = buf.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1").split("\r\n")
    m = _STATUS_LINE.match(lines[0])
    if not m:
        raise FetchFailed("malformed status line")
    status = int(m.group(1))
    location = None
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "location":
            location = value.strip()
    return HeadResult(status=status, location=location if 300 <= status < 400 else None, connected_ip=ip)
