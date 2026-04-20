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


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addrs: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        if sockaddr:
            addrs.append(sockaddr[0])
    return addrs


async def assert_public_url(url: str) -> None:
    """Raise :class:`UnsafePublicURLError` if the URL cannot be fetched safely.

    Checks:
      * Scheme is ``http`` or ``https``.
      * URL has a host component.
      * Every address the host resolves to is globally-routable unicast
        (rejects loopback, link-local, private, multicast, reserved).
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

    if literal is not None:
        if not _ip_is_public(literal):
            raise UnsafePublicURLError(
                f"Host resolves to non-public address: {literal}"
            )
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
        if not _ip_is_public(rip):
            raise UnsafePublicURLError(
                f"Host {host!r} resolves to non-public address: {rip}"
            )


async def is_public_url(url: str) -> bool:
    """Non-throwing variant of :func:`assert_public_url`."""
    try:
        await assert_public_url(url)
    except UnsafePublicURLError:
        return False
    return True
