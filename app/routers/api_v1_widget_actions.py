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
import time
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
from app.services.widget_templates import apply_widget_template, get_state_poll_config, apply_state_poll

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget-actions", tags=["widget-actions"])


def _resolve_tool_name(name: str) -> str:
    """Resolve a tool name, trying MCP server-prefixed variants if bare name fails.

    Widget templates use bare tool names (e.g., "HassTurnOff") but MCP tools
    are registered with a server prefix (e.g., "homeassistant-HassTurnOff").
    """
    if is_local_tool(name) or is_mcp_tool(name):
        return name

    # Try finding an MCP tool with any server prefix
    from app.tools.mcp import _cache as mcp_cache
    for server_name, cached in mcp_cache.items():
        prefixed = f"{server_name}-{name}"
        for tool in cached.get("tools", []):
            if tool["function"]["name"] == prefixed:
                return prefixed

    return name  # fall through — will error downstream

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

    # Resolve the actual tool name — MCP tools may be registered with a server
    # prefix (e.g., "homeassistant-HassTurnOff") but templates reference the
    # bare name ("HassTurnOff"). Try bare first, then scan MCP servers for a
    # prefixed match.
    resolved_name = _resolve_tool_name(name)

    # Resolve tool type and call it
    result: str | None = None
    error_msg: str | None = None

    if is_local_tool(resolved_name):
        try:
            result = await asyncio.wait_for(
                call_local_tool(resolved_name, args_str),
                timeout=settings.TOOL_DISPATCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            error_msg = f"Tool '{resolved_name}' timed out"
        except Exception as exc:
            error_msg = f"Tool '{resolved_name}' failed: {exc}"
    elif is_mcp_tool(resolved_name):
        try:
            result = await asyncio.wait_for(
                call_mcp_tool(resolved_name, args_str),
                timeout=settings.TOOL_DISPATCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            error_msg = f"MCP tool '{resolved_name}' timed out"
        except Exception as exc:
            error_msg = f"MCP tool '{resolved_name}' failed: {exc}"
    else:
        return WidgetActionResponse(ok=False, error=f"Unknown tool: {name}")

    if error_msg:
        return WidgetActionResponse(ok=False, error=error_msg)

    if result is None:
        return WidgetActionResponse(ok=True, envelope=None)

    # Build envelope from result
    envelope = _build_result_envelope(resolved_name, result)

    logger.info(
        "Widget action: tool=%s resolved=%s args=%s channel=%s result_preview=%.200s",
        name, resolved_name, args_str, req.channel_id, result or "",
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


def _build_result_envelope(tool_name: str, raw_result: str) -> ToolResultEnvelope:
    """Build a ToolResultEnvelope from a raw tool result string.

    Tries in order: _envelope opt-in → widget template → default envelope.
    """
    # Try to parse as JSON and check for _envelope opt-in
    try:
        parsed = json.loads(raw_result)
        if isinstance(parsed, dict) and "_envelope" in parsed:
            return _build_envelope_from_optin(parsed["_envelope"], raw_result)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try widget template from integration manifests
    widget_env = apply_widget_template(tool_name, raw_result)
    if widget_env is not None:
        return widget_env

    return _build_default_envelope(raw_result)


# ── State poll cache — deduplicates concurrent GetLiveContext calls ──

_poll_cache: dict[str, tuple[float, str]] = {}  # tool_name → (timestamp, raw_result)
_POLL_CACHE_TTL = 30.0  # seconds


class WidgetRefreshRequest(BaseModel):
    tool_name: str
    display_label: str = ""
    channel_id: uuid.UUID
    bot_id: str


@router.post("/refresh", response_model=WidgetActionResponse)
async def refresh_widget_state(req: WidgetRefreshRequest):
    """Fetch fresh state for a pinned widget by calling its state_poll tool.

    The state_poll config is declared in the widget template YAML. Results are
    cached for 30s to avoid redundant calls when multiple pinned widgets from
    the same integration refresh on page load.
    """
    # Look up state_poll config for this tool
    poll_cfg = get_state_poll_config(req.tool_name)
    if not poll_cfg:
        return WidgetActionResponse(ok=False, error=f"No state_poll config for {req.tool_name}")

    poll_tool = poll_cfg.get("tool")
    if not poll_tool:
        return WidgetActionResponse(ok=False, error="state_poll missing 'tool' field")

    # Resolve the poll tool name (may need MCP prefix)
    resolved_poll_tool = _resolve_tool_name(poll_tool)

    # Check cache — reuse recent result for the same poll tool
    now = time.monotonic()
    cached = _poll_cache.get(resolved_poll_tool)
    if cached and (now - cached[0]) < _POLL_CACHE_TTL:
        raw_result = cached[1]
        logger.debug("Widget refresh: using cached %s result (%.1fs old)", resolved_poll_tool, now - cached[0])
    else:
        # Call the poll tool
        raw_result = None
        error_msg = None

        if is_local_tool(resolved_poll_tool):
            poll_args = json.dumps(poll_cfg.get("args", {}))
            try:
                raw_result = await asyncio.wait_for(
                    call_local_tool(resolved_poll_tool, poll_args),
                    timeout=settings.TOOL_DISPATCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                error_msg = f"Poll tool '{resolved_poll_tool}' timed out"
            except Exception as exc:
                error_msg = f"Poll tool '{resolved_poll_tool}' failed: {exc}"
        elif is_mcp_tool(resolved_poll_tool):
            poll_args = json.dumps(poll_cfg.get("args", {}))
            try:
                raw_result = await asyncio.wait_for(
                    call_mcp_tool(resolved_poll_tool, poll_args),
                    timeout=settings.TOOL_DISPATCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                error_msg = f"Poll tool '{resolved_poll_tool}' timed out"
            except Exception as exc:
                error_msg = f"Poll tool '{resolved_poll_tool}' failed: {exc}"
        else:
            return WidgetActionResponse(ok=False, error=f"Unknown poll tool: {poll_tool}")

        if error_msg:
            return WidgetActionResponse(ok=False, error=error_msg)

        if raw_result is None:
            return WidgetActionResponse(ok=True, envelope=None)

        # Cache the result
        _poll_cache[resolved_poll_tool] = (now, raw_result)

    # Apply state_poll transform + template
    widget_meta = {"display_label": req.display_label, "tool_name": req.tool_name}
    envelope = apply_state_poll(req.tool_name, raw_result, widget_meta)

    if envelope is None:
        return WidgetActionResponse(ok=False, error="State poll template failed to render")

    logger.info(
        "Widget refresh: tool=%s poll_tool=%s display_label=%s",
        req.tool_name, resolved_poll_tool, req.display_label,
    )

    return WidgetActionResponse(ok=True, envelope=envelope.compact_dict())
