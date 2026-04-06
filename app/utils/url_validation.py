"""Shared SSRF protection — block requests to private/reserved IP ranges.

Used by web_search, webhook dispatcher, and any outbound HTTP caller that
takes a user-supplied URL.  Includes DNS-pinning helpers to prevent TOCTOU
(time-of-check-to-time-of-use) DNS rebinding attacks.
"""
import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_private_ip(ip_str: str) -> bool:
    """Return True if the IP address falls within a blocked (private/reserved) range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # fail-secure: block unparseable addresses
    return any(addr in net for net in _BLOCKED_NETWORKS)


def _default_port(scheme: str) -> int:
    return 80 if scheme == "http" else 443


def validate_url(url: str) -> None:
    """Raise ValueError if the URL targets a private/reserved IP address (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    # Block obvious localhost names
    if hostname in ("localhost", "0.0.0.0"):
        raise ValueError(f"Blocked: {hostname} is a local address.")
    # Resolve hostname and check all resulting IPs
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or _default_port(parsed.scheme), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname}: {exc}") from exc
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        if is_private_ip(ip_str):
            raise ValueError(
                f"URL resolves to private/reserved IP {ip_str} — request blocked (SSRF protection)"
            )


def resolve_and_pin(url: str) -> tuple[str, str]:
    """Validate URL, resolve DNS, check all IPs, return (original_url, pinned_ip).

    Prevents DNS rebinding by capturing the resolved IP at validation time
    so the caller can connect directly to it via ``pin_url``.

    Raises ValueError on scheme/hostname/private-IP failures.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    if hostname in ("localhost", "0.0.0.0"):
        raise ValueError(f"Blocked: {hostname} is a local address.")

    try:
        infos = socket.getaddrinfo(hostname, parsed.port or _default_port(parsed.scheme), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname}: {exc}") from exc

    first_valid: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        if is_private_ip(ip_str):
            raise ValueError(
                f"URL resolves to private/reserved IP {ip_str} — request blocked (SSRF protection)"
            )
        if first_valid is None:
            first_valid = ip_str

    if first_valid is None:
        raise ValueError(f"DNS returned no addresses for {hostname}")

    return url, first_valid


def pin_url(url: str, pinned_ip: str) -> tuple[str, dict[str, str]]:
    """Replace hostname with pinned IP, return (modified_url, extra_headers).

    The returned headers dict contains the ``Host`` header set to the
    original hostname so that TLS SNI and virtual-host routing still work.
    """
    parsed = urlparse(url)
    original_host = parsed.hostname or ""

    # IPv6 addresses must be bracketed in URLs per RFC 3986
    ip_for_url = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip

    # Rebuild netloc with pinned IP, preserving port if present
    if parsed.port:
        new_netloc = f"{ip_for_url}:{parsed.port}"
    else:
        new_netloc = ip_for_url

    modified = urlunparse((
        parsed.scheme,
        new_netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))
    return modified, {"Host": original_host}
