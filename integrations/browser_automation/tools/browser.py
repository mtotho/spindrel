"""Headless browser automation tools backed by the shared browser runtime."""
from __future__ import annotations

import json

from integrations.sdk import (
    current_bot_id,
    current_channel_id,
    log_outbound_request,
    register_tool as register,
    resolve_and_pin,
)

from integrations.browser_automation.manager import manager


def _owner_key() -> tuple[str, str]:
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    if not bot_id or not channel_id:
        raise RuntimeError("Headless browser tools require bot and channel context")
    return bot_id, str(channel_id)


def _validate_url(url: str) -> str:
    clean_url, _pinned_ip = resolve_and_pin(url)
    log_outbound_request(url=clean_url, method="GET", tool_name="headless_browser")
    return clean_url


_PAGE_RETURNS = {
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "title": {"type": "string"},
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "protocol": {"type": "string"},
    },
}


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_open",
        "description": "Open a fresh headless Chromium session for this bot/channel, optionally navigating to a public URL.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": [],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns=_PAGE_RETURNS)
async def headless_browser_open(url: str | None = None) -> str:
    clean_url = _validate_url(url) if url else None
    return json.dumps(await manager.open(_owner_key(), url=clean_url))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_goto",
        "description": "Navigate the current headless browser session to a public URL.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns=_PAGE_RETURNS)
async def headless_browser_goto(url: str) -> str:
    return json.dumps(await manager.goto(_owner_key(), _validate_url(url)))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_snapshot",
        "description": "Read the current headless browser page URL, title, and visible body text.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}, requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "title": {"type": "string"},
        "text": {"type": "string"},
    },
})
async def headless_browser_snapshot() -> str:
    return json.dumps(await manager.snapshot(_owner_key()))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_click",
        "description": "Click a CSS selector in the current headless browser session.",
        "parameters": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns=_PAGE_RETURNS)
async def headless_browser_click(selector: str) -> str:
    return json.dumps(await manager.click(_owner_key(), selector))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_type",
        "description": "Type text into a CSS selector in the current headless browser session.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "clear": {"type": "boolean", "default": False},
            },
            "required": ["selector", "text"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns=_PAGE_RETURNS)
async def headless_browser_type(selector: str, text: str, clear: bool = False) -> str:
    return json.dumps(await manager.type(_owner_key(), selector, text, clear=clear))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_screenshot",
        "description": "Capture a PNG screenshot of the current headless browser page.",
        "parameters": {
            "type": "object",
            "properties": {"full_page": {"type": "boolean", "default": False}},
            "required": [],
        },
    },
}, requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "image_data_url": {"type": "string"},
        "url": {"type": "string"},
        "title": {"type": "string"},
        "width": {"type": "integer"},
        "height": {"type": "integer"},
    },
})
async def headless_browser_screenshot(full_page: bool = False) -> str:
    return json.dumps(await manager.screenshot(_owner_key(), full_page=full_page))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_eval",
        "description": "Evaluate JavaScript in the current headless browser page. Use only for inspection or controlled tests.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
}, safety_tier="exec_capable", requires_bot_context=True, requires_channel_context=True)
async def headless_browser_eval(expression: str) -> str:
    return json.dumps(await manager.evaluate(_owner_key(), expression))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_close",
        "description": "Close this bot/channel's current headless browser session.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {"closed": {"type": "boolean"}},
})
async def headless_browser_close() -> str:
    return json.dumps(await manager.close(_owner_key()))


@register({
    "type": "function",
    "function": {
        "name": "headless_browser_status",
        "description": "Show headless browser sessions for this bot/channel.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}, requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {"sessions": {"type": "array"}},
})
async def headless_browser_status() -> str:
    return json.dumps(await manager.status(_owner_key()))

