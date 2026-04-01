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

# Private/internal IP networks to block (SSRF protection)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
]


def _check_ssrf(url: str) -> None:
    """Raise ValueError if URL targets a blocked internal address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked scheme: {parsed.scheme!r}. Only http/https allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("No hostname in URL.")

    # Block obvious localhost names
    if hostname in ("localhost", "0.0.0.0"):
        raise ValueError(f"Blocked: {hostname} is a local address.")

    # Resolve hostname and check all IPs
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname!r}")

    for family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise ValueError(
                    f"Blocked: {hostname} resolves to internal address {ip}."
                )


# ── web_search (dispatches based on WEB_SEARCH_MODE at call time) ─────────

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
        _check_ssrf(url)
    except ValueError as e:
        return f"Error: {e}"

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
