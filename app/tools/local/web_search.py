import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.tools.registry import register

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")

# ---------------------------------------------------------------------------
# SSRF protection — block requests to private/reserved IP ranges
# ---------------------------------------------------------------------------
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


def _is_private_ip(ip_str: str) -> bool:
    """Return True if the IP address falls within a blocked (private/reserved) range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # fail-secure: block unparseable addresses
    return any(addr in net for net in _BLOCKED_NETWORKS)


def _validate_url(url: str) -> None:
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
        if _is_private_ip(ip_str):
            raise ValueError(
                f"URL resolves to private/reserved IP {ip_str} — request blocked (SSRF protection)"
            )


# Alias for backward compatibility
_check_ssrf = _validate_url


# ── web_search (dispatches based on WEB_SEARCH_MODE at call time) ─────────────────


@register({
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information. Use when you need recent events, "
            "facts you're unsure about, or anything time-sensitive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                },
            },
            "required": ["query"],
        },
    },
})
async def web_search(query: str, num_results: int = 5) -> str:
    mode = settings.WEB_SEARCH_MODE
    if mode == "searxng":
        return await _web_search_searxng(query, num_results)
    elif mode == "ddgs":
        return await _web_search_ddgs(query, num_results)
    else:
        return json.dumps({"error": "Web search is disabled. Enable it in Settings > Web Search."})


async def _web_search_searxng(query: str, num_results: int = 5) -> str:
    """Search via self-hosted SearXNG instance."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.SEARXNG_URL}/search",
                params={"q": query, "format": "json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        return json.dumps({"error": f"Cannot connect to SearXNG at {settings.SEARXNG_URL}. Are the containers running? (COMPOSE_PROFILES=web-search)"})
    except httpx.TimeoutException:
        return json.dumps({"error": f"SearXNG request timed out ({settings.SEARXNG_URL})"})
    except httpx.HTTPStatusError as exc:
        return json.dumps({"error": f"SearXNG returned HTTP {exc.response.status_code}"})

    results = data.get("results", [])[:num_results]
    return json.dumps([
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in results
    ])


async def _web_search_ddgs(query: str, num_results: int = 5) -> str:
    """Search via ddgs (DuckDuckGo + other backends). No infrastructure required."""
    import asyncio
    from ddgs import DDGS

    try:
        results = await asyncio.to_thread(DDGS().text, query, max_results=num_results)
    except Exception as exc:
        logger.warning("ddgs search failed: %s", exc)
        return json.dumps({"error": f"Web search failed: {exc}"})
    if not results:
        return json.dumps([])
    return json.dumps([
        {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
        for r in results
    ])


# ── fetch_url (always registered) ─────────────────────────────────────────

@register({
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": "Fetch and read the full text content of a webpage URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
            },
            "required": ["url"],
        },
    },
})
async def fetch_url(url: str) -> str:
    try:
        _validate_url(url)
    except ValueError as exc:
        return f"Error: {exc}"
    try:
        return await _fetch_with_playwright(url)
    except Exception as e:
        logger.warning("Playwright fetch failed (%s), falling back to httpx: %s", type(e).__name__, e)
        return await _fetch_with_httpx(url)


async def _fetch_with_playwright(url: str) -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(settings.PLAYWRIGHT_WS_URL)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            text = await page.inner_text("body")
        finally:
            await browser.close()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = "\n".join(lines)
    if len(clean) > 4000:
        clean = clean[:4000] + "\n...(truncated)"
    return clean


async def _fetch_with_httpx(url: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()

    text = _TAG_RE.sub("", resp.text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = "\n".join(lines)
    if len(clean) > 4000:
        clean = clean[:4000] + "\n...(truncated)"
    return clean
