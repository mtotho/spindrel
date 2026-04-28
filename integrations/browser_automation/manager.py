"""Process-local Playwright session manager for headless browser tools."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.services.runtime_services import resolve_runtime_requirement
from integrations.browser_automation.config import settings


@dataclass
class BrowserSession:
    owner_key: tuple[str, str]
    playwright: Any
    browser: Any
    page: Any
    created_at: float
    last_used_at: float
    endpoint: str
    protocol: str


class HeadlessBrowserManager:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], BrowserSession] = {}
        self._lock = asyncio.Lock()

    async def open(self, owner_key: tuple[str, str], *, url: str | None = None) -> dict[str, Any]:
        await self.close(owner_key)
        endpoint, protocol = self._resolve_endpoint()
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            browser = await self._connect(playwright, endpoint, protocol)
            page = await browser.new_page()
            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            await playwright.stop()
            raise

        now = time.time()
        session = BrowserSession(
            owner_key=owner_key,
            playwright=playwright,
            browser=browser,
            page=page,
            created_at=now,
            last_used_at=now,
            endpoint=endpoint,
            protocol=protocol,
        )
        async with self._lock:
            self._sessions[owner_key] = session
        return await self._page_info(session)

    async def goto(self, owner_key: tuple[str, str], url: str) -> dict[str, Any]:
        session = await self._require(owner_key)
        await session.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return await self._page_info(session)

    async def snapshot(self, owner_key: tuple[str, str]) -> dict[str, Any]:
        session = await self._require(owner_key)
        title = await session.page.title()
        url = session.page.url
        text = await session.page.locator("body").inner_text(timeout=5000)
        return {"url": url, "title": title, "text": text[:8000]}

    async def click(self, owner_key: tuple[str, str], selector: str) -> dict[str, Any]:
        session = await self._require(owner_key)
        await session.page.click(selector, timeout=10000)
        return await self._page_info(session)

    async def type(self, owner_key: tuple[str, str], selector: str, text: str, *, clear: bool = False) -> dict[str, Any]:
        session = await self._require(owner_key)
        if clear:
            await session.page.fill(selector, text, timeout=10000)
        else:
            await session.page.type(selector, text, timeout=10000)
        return await self._page_info(session)

    async def screenshot(self, owner_key: tuple[str, str], *, full_page: bool = False) -> dict[str, Any]:
        import base64

        session = await self._require(owner_key)
        data = await session.page.screenshot(type="png", full_page=full_page)
        info = await self._page_info(session)
        info["image_data_url"] = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        return info

    async def evaluate(self, owner_key: tuple[str, str], expression: str) -> dict[str, Any]:
        session = await self._require(owner_key)
        value = await session.page.evaluate(expression)
        return {"value": value, **await self._page_info(session)}

    async def close(self, owner_key: tuple[str, str]) -> dict[str, Any]:
        async with self._lock:
            session = self._sessions.pop(owner_key, None)
        if not session:
            return {"closed": False}
        try:
            await session.browser.close()
        finally:
            await session.playwright.stop()
        return {"closed": True}

    async def status(self, owner_key: tuple[str, str] | None = None) -> dict[str, Any]:
        await self.cleanup_idle()
        sessions = []
        for key, session in self._sessions.items():
            if owner_key and key != owner_key:
                continue
            sessions.append({
                "bot_id": key[0],
                "channel_id": key[1],
                "url": session.page.url,
                "endpoint": session.endpoint,
                "protocol": session.protocol,
                "age_seconds": int(time.time() - session.created_at),
                "idle_seconds": int(time.time() - session.last_used_at),
            })
        return {"sessions": sessions}

    async def cleanup_idle(self) -> int:
        cutoff = time.time() - settings.HEADLESS_BROWSER_IDLE_TTL_SECONDS
        stale = [key for key, session in self._sessions.items() if session.last_used_at < cutoff]
        for key in stale:
            await self.close(key)
        return len(stale)

    def _resolve_endpoint(self) -> tuple[str, str]:
        if settings.HEADLESS_BROWSER_WS_URL:
            return settings.HEADLESS_BROWSER_WS_URL, "auto"
        resolution = resolve_runtime_requirement("browser_automation", "browser.playwright")
        if not resolution.endpoint:
            raise RuntimeError("No shared browser runtime is configured")
        return resolution.endpoint, resolution.protocol or "auto"

    async def _connect(self, playwright: Any, endpoint: str, protocol: str) -> Any:
        if protocol == "playwright":
            return await playwright.chromium.connect(endpoint)
        if protocol == "cdp":
            return await playwright.chromium.connect_over_cdp(endpoint)
        try:
            return await playwright.chromium.connect(endpoint)
        except Exception:
            return await playwright.chromium.connect_over_cdp(endpoint)

    async def _require(self, owner_key: tuple[str, str]) -> BrowserSession:
        await self.cleanup_idle()
        async with self._lock:
            session = self._sessions.get(owner_key)
        if not session:
            raise RuntimeError("No headless browser session is open. Call headless_browser_open first.")
        session.last_used_at = time.time()
        return session

    async def _page_info(self, session: BrowserSession) -> dict[str, Any]:
        session.last_used_at = time.time()
        viewport = session.page.viewport_size or {}
        return {
            "url": session.page.url,
            "title": await session.page.title(),
            "width": viewport.get("width"),
            "height": viewport.get("height"),
            "protocol": session.protocol,
        }


manager = HeadlessBrowserManager()

