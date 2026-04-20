"""Tools that drive the user's paired live browser via the bridge.

Each tool is a thin shim: validate args, RPC the extension, return JSON.
Real logic lives in extension/background.js.
"""

from __future__ import annotations

import json
from typing import Any

from integrations.sdk import current_bot_id, register_tool as register

from ..bridge import bridge


def _user_id_for_call() -> str:
    """Resolve the user the tool call belongs to.

    TODO: pull from request context (current_user_id ContextVar). For the
    sketch we route by bot_id so a single-user dev setup just works.
    """
    bid = current_bot_id.get() if hasattr(current_bot_id, "get") else None
    if not bid:
        raise RuntimeError("browser_live: no bot context — cannot resolve user")
    return str(bid)


@register(
    {
        "name": "browser_goto",
        "description": (
            "Navigate the user's active browser tab to a URL. Uses the user's "
            "real Chrome/Firefox session — cookies, logins, extensions all "
            "apply. Returns the final URL after redirects."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "new_tab": {"type": "boolean", "default": False},
            },
            "required": ["url"],
        },
    },
    safety_tier="mutating",
    returns={
        "type": "object",
        "properties": {
            "final_url": {"type": "string"},
            "tab_id": {"type": "integer"},
            "title": {"type": "string"},
        },
    },
)
async def browser_goto(url: str, new_tab: bool = False) -> str:
    result = await bridge.request(
        _user_id_for_call(), "goto", {"url": url, "new_tab": new_tab}
    )
    return json.dumps(result)


@register(
    {
        "name": "browser_act",
        "description": (
            "Perform an action on a CSS selector in the active tab: click, "
            "type, hover, focus, scroll_into_view. For typing use the "
            "'value' arg."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["click", "type", "hover", "focus", "scroll_into_view"],
                },
                "value": {"type": "string"},
            },
            "required": ["selector", "action"],
        },
    },
    safety_tier="mutating",
)
async def browser_act(selector: str, action: str, value: str | None = None) -> str:
    result = await bridge.request(
        _user_id_for_call(),
        "act",
        {"selector": selector, "action": action, "value": value},
    )
    return json.dumps(result)


@register(
    {
        "name": "browser_eval",
        "description": (
            "Evaluate a JS expression in the active tab and return its JSON-"
            "serialisable result. Use sparingly — prefer browser_act for "
            "UI interactions."
        ),
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
    safety_tier="exec_capable",
)
async def browser_eval(expression: str) -> str:
    result = await bridge.request(
        _user_id_for_call(), "eval", {"expression": expression}
    )
    return json.dumps(result)


@register(
    {
        "name": "browser_screenshot",
        "description": (
            "Capture a PNG screenshot of the active tab's visible region. "
            "Returns a data URL plus the tab's URL/title for context."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    safety_tier="readonly",
    returns={
        "type": "object",
        "properties": {
            "image_data_url": {"type": "string"},
            "url": {"type": "string"},
            "title": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
    },
)
async def browser_screenshot() -> str:
    result = await bridge.request(_user_id_for_call(), "screenshot", {})
    return json.dumps(result)


@register(
    {
        "name": "browser_status",
        "description": (
            "List currently paired browser connections for the calling user. "
            "Useful as a preflight check before issuing other browser_* "
            "tools."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    safety_tier="readonly",
)
async def browser_status() -> str:
    return json.dumps({"connections": bridge.connections_for(_user_id_for_call())})
