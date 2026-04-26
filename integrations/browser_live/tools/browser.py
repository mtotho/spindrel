"""Tools that drive the user's paired live browser via the bridge.

Each tool is a thin shim: validate args, RPC the extension, return JSON.
Real logic lives in extension/background.js. The bridge picks the most-
recently-paired browser; pass ``connection_id`` to target a specific one
(IDs come from ``browser_status``).
"""

from __future__ import annotations

import json

from integrations.sdk import register_tool as register

from integrations.browser_live.bridge import bridge


@register(
    {
        "type": "function",
        "function": {
            "name": "browser_goto",
            "description": (
                "Navigate the user's active browser tab to a URL. Uses the "
                "user's real Chrome session — cookies, logins, extensions "
                "all apply. Returns the final URL after redirects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "new_tab": {"type": "boolean", "default": False},
                    "connection_id": {"type": "string"},
                },
                "required": ["url"],
            },
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
async def browser_goto(
    url: str, new_tab: bool = False, connection_id: str | None = None
) -> str:
    result = await bridge.request(
        "goto",
        {"url": url, "new_tab": new_tab},
        connection_id=connection_id,
        timeout_ms=30000,
    )
    return json.dumps(result)


@register(
    {
        "type": "function",
        "function": {
            "name": "browser_act",
            "description": (
                "Perform an action on a CSS selector in the active tab: "
                "click, type, hover, focus, scroll_into_view. For typing, "
                "set 'value'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "click",
                            "type",
                            "hover",
                            "focus",
                            "scroll_into_view",
                        ],
                    },
                    "value": {"type": "string"},
                    "connection_id": {"type": "string"},
                },
                "required": ["selector", "action"],
            },
        },
    },
    safety_tier="mutating",
)
async def browser_act(
    selector: str,
    action: str,
    value: str | None = None,
    connection_id: str | None = None,
) -> str:
    result = await bridge.request(
        "act",
        {"selector": selector, "action": action, "value": value},
        connection_id=connection_id,
    )
    return json.dumps(result)


@register(
    {
        "type": "function",
        "function": {
            "name": "browser_eval",
            "description": (
                "Evaluate a JS expression in the active tab and return its "
                "JSON-serialisable result. Use sparingly — prefer "
                "browser_act for UI interactions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "connection_id": {"type": "string"},
                },
                "required": ["expression"],
            },
        },
    },
    safety_tier="exec_capable",
)
async def browser_eval(expression: str, connection_id: str | None = None) -> str:
    result = await bridge.request(
        "eval", {"expression": expression}, connection_id=connection_id
    )
    return json.dumps(result)


@register(
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": (
                "Capture a PNG screenshot of the active tab's visible "
                "region. Returns a data URL plus the tab's URL/title for "
                "context."
            ),
            "parameters": {
                "type": "object",
                "properties": {"connection_id": {"type": "string"}},
                "required": [],
            },
        },
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
async def browser_screenshot(connection_id: str | None = None) -> str:
    result = await bridge.request("screenshot", {}, connection_id=connection_id)
    return json.dumps(result)


@register(
    {
        "type": "function",
        "function": {
            "name": "browser_status",
            "description": (
                "List currently paired browser connections. Useful as a "
                "preflight check before issuing other browser_* tools, "
                "and to discover connection_ids for multi-browser routing."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    safety_tier="readonly",
    returns={
        "type": "object",
        "properties": {
            "connections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string"},
                        "label": {"type": "string"},
                        "pending": {"type": "integer"},
                    },
                },
            },
        },
    },
)
async def browser_status() -> str:
    return json.dumps({"connections": bridge.list_connections()})
