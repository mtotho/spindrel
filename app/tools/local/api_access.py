"""Local tools: list_api_endpoints + call_api — direct API access for bots with scoped keys."""

import json
import logging
from typing import Any

from app.agent.context import current_bot_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "list_api_endpoints",
        "description": (
            "List API endpoints available to this bot, filtered by its scoped API key permissions. "
            "Optionally filter by a specific scope prefix (e.g. 'channels', 'tasks'). "
            "The results are valid for BOTH server-side `call_api` AND widget-side `window.spindrel.api()` — "
            "your scoped key is the common denominator. Call this before writing an HTML widget so you "
            "bind to paths your widget can actually hit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Optional scope prefix to filter results (e.g. 'channels', 'tasks:read').",
                },
            },
        },
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "endpoints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "path": {"type": "string"},
                    "description": {"type": "string"},
                    "params": {"type": "object"},
                    "body": {"type": "object"},
                    "response": {"type": "object"},
                    "notes": {"type": "string"},
                },
                "required": ["method", "path"],
            },
        },
        "count": {"type": "integer"},
        "scopes": {"type": "array", "items": {"type": "string"}},
        "message": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def list_api_endpoints(scope: str = "") -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    if not bot.api_permissions:
        return json.dumps({"error": "This bot has no API access configured. Ask an admin to set api_permissions."}, ensure_ascii=False)

    from app.services.api_keys import ENDPOINT_CATALOG, has_scope

    bot_scopes = bot.api_permissions
    filtered = []
    for ep in ENDPOINT_CATALOG:
        ep_scope = ep.get("scope") or ""
        if not ep_scope or not has_scope(bot_scopes, ep_scope):
            continue
        if scope and not ep_scope.startswith(scope):
            continue
        entry = {
            "method": ep["method"],
            "path": ep["path"],
            "description": ep.get("description", ""),
        }
        if ep.get("params"):
            entry["params"] = ep["params"]
        if ep.get("body"):
            entry["body"] = ep["body"]
        if ep.get("response"):
            entry["response"] = ep["response"]
        if ep.get("notes"):
            entry["notes"] = ep["notes"]
        filtered.append(entry)

    if not filtered:
        return json.dumps({
            "endpoints": [],
            "message": f"No endpoints match scope filter '{scope}'." if scope else "No endpoints available for your permissions.",
            "scopes": bot_scopes,
        }, ensure_ascii=False)

    return json.dumps({"endpoints": filtered, "count": len(filtered), "scopes": bot_scopes}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "call_api",
        "description": (
            "Call an agent server API endpoint using this bot's scoped API key. "
            "The request runs in-process with full auth/validation. "
            "Use list_api_endpoints() first to see available endpoints."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "description": "HTTP method.",
                },
                "path": {
                    "type": "string",
                    "description": "API path starting with /api/ (e.g. '/api/v1/channels').",
                },
                "body": {
                    "type": ["object", "array", "string", "null"],
                    "description": (
                        "Optional JSON request body. Prefer a structured object/array. "
                        "A JSON string is still accepted for backward compatibility."
                    ),
                },
            },
            "required": ["method", "path"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "body": {},
        "error": {"type": "string"},
    },
})
async def call_api(method: str, path: str, body: Any = "") -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)

    # Safety: only allow /api/ paths and /chat, /bots paths
    if not (path.startswith("/api/") or path.startswith("/chat") or path.startswith("/bots")):
        return json.dumps({"error": "Path must start with /api/, /chat, or /bots. Arbitrary paths are not allowed."}, ensure_ascii=False)

    # Get API key
    from app.db.engine import async_session
    from app.services.api_keys import get_bot_api_key_value
    async with async_session() as db:
        key_value = await get_bot_api_key_value(db, bot_id)

    if not key_value:
        return json.dumps({"error": "No API key configured for this bot. Ask an admin to assign one."}, ensure_ascii=False)

    # Parse body if provided
    request_body = None
    if body not in ("", None):
        if isinstance(body, str):
            try:
                request_body = json.loads(body)
            except json.JSONDecodeError:
                return json.dumps({"error": f"Invalid JSON body: {body[:200]}"}, ensure_ascii=False)
        elif isinstance(body, (dict, list)):
            request_body = body
        else:
            return json.dumps(
                {"error": f"Body must be a JSON object, array, string, or null; got {type(body).__name__}."},
                ensure_ascii=False,
            )

    # Make in-process request via ASGI transport
    try:
        import httpx
        from httpx import ASGITransport
        # Lazy import to avoid circular imports
        from app.main import app as asgi_app

        transport = ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.request(
                method=method.upper(),
                url=path,
                json=request_body,
                headers={"Authorization": f"Bearer {key_value}"},
                timeout=30.0,
            )

        # Parse response
        try:
            resp_body = response.json()
        except Exception:
            resp_body = response.text

        result = {"status": response.status_code, "body": resp_body}

        # Truncate very large responses
        result_str = json.dumps(result, ensure_ascii=False)
        if len(result_str) > 50000:
            result["body"] = "[Response truncated — too large. Try a more specific query or add filters.]"
            result_str = json.dumps(result, ensure_ascii=False)

        return result_str

    except Exception as e:
        logger.warning("call_api failed: %s %s — %s", method, path, e, exc_info=True)
        return json.dumps({"error": f"Request failed: {str(e)}"}, ensure_ascii=False)
