"""Tools listing + direct execution: /tools, /tools/{tool_id}, /tools/{tool_name}/execute."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, ToolEmbedding, WidgetTemplatePackage
from app.dependencies import ApiKeyAuth, get_db, require_scopes
from app.services.api_keys import has_scope
from app.services.tool_execution import (
    execute_tool_with_context,
    validate_tool_context_requirements,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ActiveWidgetPackageOut(BaseModel):
    id: str
    name: str
    source: str


class ToolOut(BaseModel):
    id: str
    tool_key: str
    tool_name: str
    server_name: Optional[str] = None
    source_dir: Optional[str] = None
    source_integration: Optional[str] = None
    source_file: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[dict] = None
    schema_: Optional[dict] = None
    indexed_at: datetime
    active_widget_package: Optional[ActiveWidgetPackageOut] = None
    widget_package_count: int = 0
    requires_bot_context: bool = False
    requires_channel_context: bool = False

    model_config = {"from_attributes": True}


class ToolExecuteRequest(BaseModel):
    arguments: dict[str, Any] = {}
    # Optional agent context to set during tool invocation. Tools that read
    # ``current_bot_id`` / ``current_channel_id`` (most local tools) error out
    # with "No bot context available." when these are unset. The dev-panel
    # sandbox passes the user-selected bot/channel through here so the tool
    # behaves identically to an LLM-driven call.
    bot_id: Optional[str] = None
    channel_id: Optional[str] = None


class ToolExecuteResponse(BaseModel):
    tool_name: str
    result: Any
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/tools", response_model=list[ToolOut])
async def admin_list_tools(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("tools:read")),
):
    """List all indexed tools."""
    rows = (await db.execute(
        select(ToolEmbedding)
        .order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
    )).scalars().all()

    active_by_tool, count_by_tool = await _widget_package_index(db)
    return [_to_out(r, active_by_tool, count_by_tool) for r in rows]


async def _widget_package_index(
    db: AsyncSession,
) -> tuple[dict[str, WidgetTemplatePackage], dict[str, int]]:
    """Return (active_by_tool, count_by_tool) for the list endpoint."""
    rows = (await db.execute(
        select(WidgetTemplatePackage).where(
            WidgetTemplatePackage.is_orphaned.is_(False),
        )
    )).scalars().all()
    active: dict[str, WidgetTemplatePackage] = {}
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.tool_name] = counts.get(row.tool_name, 0) + 1
        if row.is_active:
            active[row.tool_name] = row
    return active, counts


@router.get("/tools/{tool_id}", response_model=ToolOut)
async def admin_get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("tools:read")),
):
    """Get a single tool by ID (UUID) or tool_key."""
    # Try UUID first
    row = None
    try:
        uid = UUID(tool_id)
        row = await db.get(ToolEmbedding, uid)
    except ValueError:
        pass

    # Fall back to tool_key lookup
    if not row:
        row = (await db.execute(
            select(ToolEmbedding).where(ToolEmbedding.tool_key == tool_id)
        )).scalar_one_or_none()

    # Fall back to tool_name lookup
    if not row:
        row = (await db.execute(
            select(ToolEmbedding).where(ToolEmbedding.tool_name == tool_id)
        )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Tool not found")

    active_by_tool, count_by_tool = await _widget_package_index(db)
    return _to_out(row, active_by_tool, count_by_tool)


@router.post("/tools/{tool_name}/execute", response_model=ToolExecuteResponse)
async def admin_execute_tool(
    tool_name: str,
    body: ToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
    auth: Union[ApiKeyAuth, Any] = Depends(require_scopes("tools:execute")),
):
    """Execute a local tool directly with the given arguments.

    Only local (Python) tools are supported — MCP and client tools cannot be
    executed through this endpoint.  Returns the raw tool result as JSON.

    Bot-scoped API keys are restricted to the bot's configured local_tools.
    Admin keys have unrestricted access.
    """
    from app.tools.registry import is_local_tool
    from app.tools.mcp import is_mcp_tool

    args_json = json.dumps(body.arguments)

    validate_tool_context_requirements(
        tool_name,
        bot_id=body.bot_id,
        channel_id=body.channel_id,
    )

    if is_local_tool(tool_name):
        if isinstance(auth, ApiKeyAuth) and not has_scope(auth.scopes, "admin"):
            if not has_scope(auth.scopes, "tools:execute"):
                raise HTTPException(status_code=403, detail="Missing tools:execute scope")
            allowed = await _resolve_bot_tools(db, auth.key_id)
            if allowed is not None and tool_name not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Bot does not have access to tool '{tool_name}'",
                )
        logger.info("Direct tool execute (local): %s args=%s", tool_name, args_json[:200])
    elif is_mcp_tool(tool_name):
        if isinstance(auth, ApiKeyAuth) and not has_scope(auth.scopes, "admin"):
            raise HTTPException(
                status_code=403,
                detail="MCP tools can only be executed by admin keys from this endpoint",
            )
        logger.info("Direct tool execute (mcp): %s args=%s", tool_name, args_json[:200])
    else:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    parsed, _raw = await execute_tool_with_context(
        tool_name,
        body.arguments,
        bot_id=body.bot_id,
        channel_id=body.channel_id,
    )

    # Try to parse as JSON for structured output
    if isinstance(parsed, dict) and "error" in parsed:
        return ToolExecuteResponse(tool_name=tool_name, result=parsed, error=parsed["error"])
    return ToolExecuteResponse(tool_name=tool_name, result=parsed)


async def _resolve_bot_tools(db: AsyncSession, key_id: UUID) -> set[str] | None:
    """Resolve the full set of local tools a bot can access, given its API key ID.

    Returns None if the key doesn't belong to a bot (allows unrestricted access
    for non-bot scoped keys like integration keys).
    """
    # Find the bot that owns this API key
    row = (await db.execute(
        select(BotRow.id).where(BotRow.api_key_id == key_id)
    )).scalar_one_or_none()
    if row is None:
        return None  # Not a bot key — no bot-level restriction

    bot_id = row
    # Get bot config from registry
    from app.agent.bots import _registry
    bot = _registry.get(bot_id)
    if bot is None:
        return set()  # Bot not in registry — deny all

    # Start with the bot's base local_tools + pinned_tools
    allowed = set(bot.local_tools)
    allowed.update(bot.pinned_tools)

    return allowed


def _to_out(
    row: ToolEmbedding,
    active_by_tool: dict[str, WidgetTemplatePackage] | None = None,
    count_by_tool: dict[str, int] | None = None,
) -> ToolOut:
    from app.tools.registry import get_tool_context_requirements

    schema = row.schema_ or {}
    fn = schema.get("function", {})
    active_by_tool = active_by_tool or {}
    count_by_tool = count_by_tool or {}

    # Look up by bare tool name first, then MCP-prefixed fallback (matches resolver).
    bare_name = row.tool_name.split("-", 1)[1] if "-" in row.tool_name else None
    active = active_by_tool.get(row.tool_name) or (
        active_by_tool.get(bare_name) if bare_name else None
    )
    count = count_by_tool.get(row.tool_name, 0) + (
        count_by_tool.get(bare_name, 0) if bare_name else 0
    )

    requires_bot, requires_channel = get_tool_context_requirements(row.tool_name)

    return ToolOut(
        id=str(row.id),
        tool_key=row.tool_key,
        tool_name=row.tool_name,
        server_name=row.server_name,
        source_dir=row.source_dir,
        source_integration=row.source_integration,
        source_file=row.source_file,
        description=fn.get("description"),
        parameters=fn.get("parameters"),
        schema_=schema,
        indexed_at=row.indexed_at,
        active_widget_package=ActiveWidgetPackageOut(
            id=str(active.id), name=active.name, source=active.source,
        ) if active is not None else None,
        widget_package_count=count,
        requires_bot_context=requires_bot,
        requires_channel_context=requires_channel,
    )
