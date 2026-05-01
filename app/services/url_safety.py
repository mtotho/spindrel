"""SSRF-safe URL validation.

The server sometimes fetches URLs on behalf of a bot / LLM response
(e.g. ``generate_image`` downloads the URL the provider returned).
Without this guard an attacker-controlled response can coerce the
server into requesting internal services — cloud metadata
(169.254.169.254), localhost-bound admin panels, RFC1918 peers, etc.

``assert_public_url`` resolves the host and rejects the request if
any resulting address is not globally-routable unicast. It is the
single source of truth for outbound-fetch allowlisting — call it
before any ``httpx`` / ``aiohttp`` fetch that takes a URL from an
untrusted source.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

__all__ = ["UnsafePublicURLError", "assert_public_url", "is_public_url"]


class UnsafePublicURLError(ValueError):
    """Raised when a URL cannot safely be fetched from the server."""


_ALLOWED_SCHEMES: tuple[str, ...] = ("http", "https")


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _classify_blocked(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_loopback: bool,
    allow_private: bool,
) -> str | None:
    """Return a short reason label if ``ip`` should be blocked, else None.

    Order matters — the most specific / most informative label wins so error
    messages like "link-local" surface the actual risk (cloud metadata)
    rather than the generic "private" bucket. The opt-ins let trusted
    callers (MCP servers a self-hoster deliberately runs on the LAN,
    integrations targeting localhost) lift specific bands of the
    default-deny without disabling the rest of the guard.
    """
    if ip.is_loopback:
        return None if allow_loopback else "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved:
        return "reserved"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_private:
        return None if allow_private else "private"
    if isinstance(ip, ipaddress.IPv4Address):
        if ipaddress.IPv4Address("100.64.0.0") <= ip <= ipaddress.IPv4Address("100.127.255.255"):
            return None if allow_private else "cgnat"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _classify_blocked(
            ip.ipv4_mapped,
            allow_loopback=allow_loopback,
            allow_private=allow_private,
        )
    return None


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addrs: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        if sockaddr:
            addrs.append(sockaddr[0])
    return addrs


async def assert_public_url(
    url: str,
    *,
    allow_loopback: bool = False,
    allow_private: bool = False,
) -> None:
    """Raise :class:`UnsafePublicURLError` if the URL cannot be fetched safely.

    Checks:
      * Scheme is ``http`` or ``https``.
      * URL has a host component.
      * Every address the host resolves to is globally-routable unicast
        (rejects loopback, link-local, private, multicast, reserved, CGNAT,
        and IPv4-mapped IPv6 of any of the above).

    Operator opt-ins:
      * ``allow_loopback`` — permit ``127.0.0.0/8`` and ``::1`` (use only
        when localhost reach is intentional, e.g. an MCP server bundled with
        the same host).
      * ``allow_private`` — permit RFC1918, IPv6 ULA, and CGNAT (use only
        when LAN reach is intentional, e.g. a household self-hoster's
        internal services).
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise UnsafePublicURLError(f"Malformed URL: {url!r}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafePublicURLError(
            f"Scheme {scheme!r} not allowed (allowed: {_ALLOWED_SCHEMES})"
        )

    host = parsed.hostname
    if not host:
        raise UnsafePublicURLError("URL has no host component")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    def _check(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        reason = _classify_blocked(
            ip, allow_loopback=allow_loopback, allow_private=allow_private,
        )
        if reason is not None:
            raise UnsafePublicURLError(
                f"Host {host!r} resolves to non-public address {ip} ({reason})"
            )

    if literal is not None:
        _check(literal)
        return

    try:
        resolved = await _resolve(host)
    except OSError as exc:
        raise UnsafePublicURLError(f"Cannot resolve host {host!r}: {exc}") from exc

    if not resolved:
        raise UnsafePublicURLError(f"Host {host!r} did not resolve")

    for raw in resolved:
        bare = raw.split("%", 1)[0]
        try:
            rip = ipaddress.ip_address(bare)
        except ValueError as exc:
            raise UnsafePublicURLError(
                f"Resolved address {raw!r} is not a valid IP"
            ) from exc
        _check(rip)


async def is_public_url(
    url: str,
    *,
    allow_loopback: bool = False,
    allow_private: bool = False,
) -> bool:
    """Non-throwing variant of :func:`assert_public_url`."""
    try:
        await assert_public_url(
            url, allow_loopback=allow_loopback, allow_private=allow_private,
        )
    except UnsafePublicURLError:
        return False
    return True
