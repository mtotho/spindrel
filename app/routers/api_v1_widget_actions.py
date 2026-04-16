"""Widget action endpoint — dispatches interactive widget actions.

POST /api/v1/widget-actions

When a user interacts with an interactive component (toggle, button, select, etc.)
in a tool result widget, the frontend sends the action here. Two dispatch modes:

- dispatch:"tool" — calls the named tool through the standard tool dispatch pipeline
  (policy checks, recording, envelope building). This is the default and preferred path.
- dispatch:"api" — proxies a request to an allowlisted internal API endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.tools.mcp import call_mcp_tool, get_mcp_server_for_tool, is_mcp_tool
from app.tools.registry import call_local_tool, is_local_tool
from app.agent.tool_dispatch import (
    ToolResultEnvelope,
    _build_default_envelope,
    _build_envelope_from_optin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget-actions", tags=["widget-actions"])

# ── Allowlisted internal API path prefixes for dispatch:"api" ──
_API_ALLOWLIST = [
    "/api/v1/admin/tasks",
    "/api/v1/channels",
]


class WidgetActionRequest(BaseModel):
    dispatch: Literal["tool", "api"] = "tool"
    # For tool dispatch
    tool: str | None = None
    args: dict = {}
    # For API dispatch
    endpoint: str | None = None
    method: str = "POST"
    body: dict | None = None
    # Context
    channel_id: uuid.UUID
    bot_id: str
    source_record_id: uuid.UUID | None = None


class WidgetActionResponse(BaseModel):
    ok: bool
    envelope: dict | None = None
    error: str | None = None
    api_response: dict | None = None


@router.post("", response_model=WidgetActionResponse)
async def dispatch_widget_action(req: WidgetActionRequest):
    """Dispatch a widget action — tool call or API proxy."""

    if req.dispatch == "tool":
        return await _dispatch_tool(req)
    elif req.dispatch == "api":
        return await _dispatch_api(req)
    else:
        raise HTTPException(400, f"Unknown dispatch type: {req.dispatch}")


async def _dispatch_tool(req: WidgetActionRequest) -> WidgetActionResponse:
    """Call a tool and return its envelope."""
    if not req.tool:
        return WidgetActionResponse(ok=False, error="Missing 'tool' field for tool dispatch")

    name = req.tool
    args_str = json.dumps(req.args) if req.args else "{}"

    # Resolve tool type and call it
    result: str | None = None
    error_msg: str | None = None

    if is_local_tool(name):
        try:
            result = await asyncio.wait_for(
                call_local_tool(name, args_str),
                timeout=settings.TOOL_DISPATCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            error_msg = f"Tool '{name}' timed out"
        except Exception as exc:
            error_msg = f"Tool '{name}' failed: {exc}"
    elif is_mcp_tool(name):
        try:
            result = await asyncio.wait_for(
                call_mcp_tool(name, args_str),
                timeout=settings.TOOL_DISPATCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            error_msg = f"MCP tool '{name}' timed out"
        except Exception as exc:
            error_msg = f"MCP tool '{name}' failed: {exc}"
    else:
        return WidgetActionResponse(ok=False, error=f"Unknown tool: {name}")

    if error_msg:
        return WidgetActionResponse(ok=False, error=error_msg)

    if result is None:
        return WidgetActionResponse(ok=True, envelope=None)

    # Build envelope from result
    envelope = _build_result_envelope(result)

    logger.info(
        "Widget action: tool=%s channel=%s bot=%s source=%s",
        name, req.channel_id, req.bot_id, req.source_record_id,
    )

    return WidgetActionResponse(ok=True, envelope=envelope.compact_dict())


async def _dispatch_api(req: WidgetActionRequest) -> WidgetActionResponse:
    """Proxy an API request to an allowlisted internal endpoint."""
    if not req.endpoint:
        return WidgetActionResponse(ok=False, error="Missing 'endpoint' field for API dispatch")

    # Validate against allowlist
    if not any(req.endpoint.startswith(prefix) for prefix in _API_ALLOWLIST):
        return WidgetActionResponse(
            ok=False,
            error=f"Endpoint '{req.endpoint}' is not in the widget action allowlist",
        )

    # Use httpx to proxy the request to ourselves
    import httpx

    base_url = f"http://127.0.0.1:{settings.PORT}"
    method = req.method.upper()
    url = f"{base_url}{req.endpoint}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, json=req.body)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                data = {"text": resp.text}
    except httpx.HTTPStatusError as exc:
        return WidgetActionResponse(ok=False, error=f"API error: {exc.response.status_code}")
    except Exception as exc:
        return WidgetActionResponse(ok=False, error=f"API request failed: {exc}")

    return WidgetActionResponse(ok=True, api_response=data)


def _build_result_envelope(raw_result: str) -> ToolResultEnvelope:
    """Build a ToolResultEnvelope from a raw tool result string."""
    # Try to parse as JSON and check for _envelope opt-in
    try:
        parsed = json.loads(raw_result)
        if isinstance(parsed, dict) and "_envelope" in parsed:
            return _build_envelope_from_optin(parsed["_envelope"], raw_result)
    except (json.JSONDecodeError, TypeError):
        pass

    return _build_default_envelope(raw_result)
