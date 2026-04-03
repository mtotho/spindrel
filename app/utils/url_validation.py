"""Shared SSRF protection — block requests to private/reserved IP ranges.

Used by web_search, webhook dispatcher, and any outbound HTTP caller that
takes a user-supplied URL.
"""
import ipaddress
import socket
from urllib.parse import urlparse

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
        infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname}: {exc}") from exc
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        if is_private_ip(ip_str):
            raise ValueError(
                f"URL resolves to private/reserved IP {ip_str} — request blocked (SSRF protection)"
            )
