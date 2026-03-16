import json
import logging
import re

import httpx

from app.config import settings
from app.tools.registry import register

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


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
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])[:num_results]
    return json.dumps([
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in results
    ])


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
