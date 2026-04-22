from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException


def resolve_tool_name(tool_name: str) -> str:
    """Return the canonical executable tool name for local or MCP tools."""
    from app.tools.mcp import is_mcp_tool, resolve_mcp_tool_name
    from app.tools.registry import is_local_tool

    if is_local_tool(tool_name) or is_mcp_tool(tool_name):
        return tool_name

    return resolve_mcp_tool_name(tool_name) or tool_name


def _parse_channel_uuid(channel_id: str | None) -> UUID | None:
    if not channel_id:
        return None
    try:
        return UUID(channel_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"channel_id '{channel_id}' is not a valid UUID.",
        ) from exc


def validate_tool_context_requirements(
    tool_name: str,
    *,
    bot_id: str | None,
    channel_id: str | None,
) -> tuple[str, bool, bool, UUID | None]:
    from app.agent.bots import _registry as _bot_registry
    from app.tools.registry import get_tool_context_requirements

    resolved_tool_name = resolve_tool_name(tool_name)
    requires_bot, requires_channel = get_tool_context_requirements(resolved_tool_name)
    if requires_bot and not bot_id:
        raise HTTPException(
            status_code=400,
            detail="This tool requires bot context. Pass source_bot_id in the request body.",
        )
    if requires_channel and not channel_id:
        raise HTTPException(
            status_code=400,
            detail="This tool requires channel context. Pass source_channel_id in the request body.",
        )
    if bot_id and bot_id not in _bot_registry:
        raise HTTPException(status_code=400, detail=f"Unknown bot_id '{bot_id}'.")
    return resolved_tool_name, requires_bot, requires_channel, _parse_channel_uuid(channel_id)


async def execute_tool_with_context(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    bot_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[Any, str]:
    from app.agent.context import current_bot_id, current_channel_id
    from app.tools.mcp import call_mcp_tool, is_mcp_tool
    from app.tools.registry import call_local_tool, is_local_tool

    resolved_tool_name, _requires_bot, _requires_channel, channel_uuid = validate_tool_context_requirements(
        tool_name,
        bot_id=bot_id,
        channel_id=channel_id,
    )
    args_json = json.dumps(arguments or {})

    bot_token = current_bot_id.set(bot_id) if bot_id else None
    channel_token = current_channel_id.set(channel_uuid) if channel_uuid else None
    try:
        if is_local_tool(resolved_tool_name):
            raw = await call_local_tool(resolved_tool_name, args_json)
        elif is_mcp_tool(resolved_tool_name):
            raw = await call_mcp_tool(resolved_tool_name, args_json)
        else:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    finally:
        if bot_token is not None:
            current_bot_id.reset(bot_token)
        if channel_token is not None:
            current_channel_id.reset(channel_token)

    try:
        return json.loads(raw), raw
    except (json.JSONDecodeError, TypeError):
        return raw, raw
