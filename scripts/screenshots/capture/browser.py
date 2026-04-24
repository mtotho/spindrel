"""Playwright context helpers.

Two concerns live here:
1. Seeding localStorage under the Zustand persist key ``agent-auth`` so the
   app mounts already-authenticated. Verified against
   ``ui/src/stores/auth.ts:40,88-89``.
2. Installing a ``spindrel:ready`` counter on ``window`` so specs can wait on
   widget readiness instead of iframe ``onload``. Verified against
   ``ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx:191,3099``.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, async_playwright


@dataclass
class AuthBundle:
    api_url: str
    access_token: str
    refresh_token: str
    user: dict


# Poll both ``postMessage`` payloads and iframes-that-have-mounted to build a
# best-effort ready counter. The interactive HTML renderer fires
# ``{type: "spindrel:ready"}``; native widgets mount as React components with
# no postMessage but appear in the DOM immediately. The counter is cheap and
# accurate enough for the wait-for gate.
READY_COUNTER_SCRIPT = """
window.__spindrel_ready = 0;
window.addEventListener("message", (e) => {
  const d = e && e.data;
  if (d && (d.type === "spindrel:ready" || d.kind === "spindrel:ready")) {
    window.__spindrel_ready += 1;
  }
});
// Also expose a helper that counts already-mounted pin tiles so non-iframe
// (native) widgets don't starve the gate.
window.__spindrel_pin_count = () => {
  try {
    return document.querySelectorAll("[data-pin-id]").length;
  } catch {
    return 0;
  }
};
"""


def _storage_init_script(*, ui_base: str, bundle: AuthBundle) -> str:
    state = {
        "serverUrl": bundle.api_url,
        "apiKey": "",
        "accessToken": bundle.access_token,
        "refreshToken": bundle.refresh_token,
        "user": bundle.user,
        "isConfigured": True,
    }
    zustand_payload = json.dumps({"state": state, "version": 0})
    # Zustand persist stores a JSON string under ``agent-auth``.
    return f"""
try {{
  localStorage.setItem("agent-auth", {json.dumps(zustand_payload)});
}} catch (e) {{
  console.error("seed agent-auth failed", e);
}}
"""


def _dev_panel_context_script(*, bot_id: str, channel_id: str) -> str:
    payload = json.dumps({"bot_id": bot_id, "channel_id": channel_id})
    return f"""
try {{
  localStorage.setItem("spindrel:widgets:dev:context", {json.dumps(payload)});
}} catch (e) {{}}
"""


@asynccontextmanager
async def browser_context(
    *,
    ui_base: str,
    bundle: AuthBundle,
    viewport: dict,
    color_scheme: str = "light",
    extra_init_scripts: list[str] | None = None,
) -> AsyncIterator[tuple[Browser, BrowserContext]]:
    """Yield an authed Playwright browser + context for one capture batch."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=viewport,
            color_scheme=color_scheme,
            base_url=ui_base,
        )
        await context.add_init_script(_storage_init_script(ui_base=ui_base, bundle=bundle))
        await context.add_init_script(READY_COUNTER_SCRIPT)
        for script in extra_init_scripts or []:
            await context.add_init_script(script)
        try:
            yield browser, context
        finally:
            await context.close()
            await browser.close()
