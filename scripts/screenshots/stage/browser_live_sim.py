"""Playwright-backed extension simulator for the browser_live integration.

The browser_live integration normally talks to a paired Chrome MV3 extension
over a WebSocket. For the screenshot pipeline we don't want to require a
hand-paired browser, so this simulator stands in for the extension: it opens
a real Playwright Chromium, connects to ``/integrations/browser_live/ws``
with a fresh pairing token, and translates the bridge's RPC verbs onto
Playwright Page APIs.

When the bot's ``browser_screenshot`` tool fires, the bridge sends an
``op=screenshot`` RPC; this simulator replies with a real PNG of the active
Chromium tab.

Usage (typically called by ``stage_integration_chat`` as a subprocess):

    python -m scripts.screenshots.stage.browser_live_sim \\
        --api-url http://10.10.30.208:18000 \\
        --token <PAIRING_TOKEN> \\
        --start-url https://example.com \\
        [--headless]

The simulator prints ``READY connection_id=<id>`` to stdout once paired and
keeps running until killed (SIGTERM/SIGINT).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import signal
import sys
from typing import Any

import websockets
from playwright.async_api import Page, async_playwright

logger = logging.getLogger("browser_live_sim")


async def _op_status(page: Page, args: dict) -> dict:
    return {"connections": [{"label": "screenshot-sim"}]}


async def _op_goto(page: Page, args: dict) -> dict:
    url = args.get("url") or ""
    new_tab = bool(args.get("new_tab"))
    if new_tab:
        page = await page.context.new_page()
    await page.goto(url, wait_until="load", timeout=30000)
    return {"url": page.url, "title": await page.title()}


async def _op_screenshot(page: Page, args: dict) -> dict:
    png = await page.screenshot(full_page=False)
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return {
        "data_url": data_url,
        "url": page.url,
        "title": await page.title(),
    }


async def _op_eval(page: Page, args: dict) -> dict:
    script = args.get("script") or "null"
    result = await page.evaluate(f"() => {{ return {script}; }}")
    return {"result": result}


async def _op_act(page: Page, args: dict) -> dict:
    selector = args.get("selector") or ""
    action = (args.get("action") or "click").lower()
    value = args.get("value")
    if action == "click":
        await page.click(selector, timeout=10000)
    elif action == "type":
        await page.fill(selector, value or "", timeout=10000)
    elif action == "select":
        await page.select_option(selector, value=value, timeout=10000)
    else:
        raise RuntimeError(f"unsupported act: {action}")
    return {"ok": True, "selector": selector, "action": action}


_OPS = {
    "status": _op_status,
    "goto": _op_goto,
    "screenshot": _op_screenshot,
    "eval": _op_eval,
    "act": _op_act,
}


async def _serve(api_url: str, token: str, *, start_url: str, headless: bool) -> None:
    ws_url = api_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/integrations/browser_live/ws?token={token}&label=screenshot-sim"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        await page.goto(start_url, wait_until="load", timeout=30000)

        async with websockets.connect(ws_url, ping_interval=20) as ws:
            hello = json.loads(await ws.recv())
            conn_id = hello.get("connection_id", "?")
            print(f"READY connection_id={conn_id}", flush=True)

            stop = asyncio.Event()

            def _stop(*_: Any) -> None:
                stop.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _stop)

            async def _pump() -> None:
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    rid = msg.get("request_id")
                    op = msg.get("op")
                    args = msg.get("args") or {}
                    handler = _OPS.get(op)
                    reply: dict
                    if not handler:
                        reply = {"request_id": rid, "error": f"unknown op {op!r}"}
                    else:
                        try:
                            result = await handler(page, args)
                            reply = {"request_id": rid, "result": result}
                        except Exception as e:
                            logger.exception("op %s failed", op)
                            reply = {"request_id": rid, "error": str(e)}
                    await ws.send(json.dumps(reply))

            pump_task = asyncio.create_task(_pump())
            await stop.wait()
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass

        await browser.close()


def main() -> int:
    p = argparse.ArgumentParser(prog="browser_live_sim")
    p.add_argument("--api-url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--start-url", default="https://example.com")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s browser_live_sim %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(
            _serve(
                args.api_url,
                args.token,
                start_url=args.start_url,
                headless=args.headless,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
