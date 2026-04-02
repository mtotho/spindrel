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

from app.db.models import Bot as BotRow, ToolEmbedding
from app.dependencies import ApiKeyAuth, get_db, verify_auth_or_user
from app.services.api_keys import has_scope

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

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

    model_config = {"from_attributes": True}


class ToolExecuteRequest(BaseModel):
    arguments: dict[str, Any] = {}


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
    _auth: str = Depends(verify_auth_or_user),
):
    """List all indexed tools."""
    rows = (await db.execute(
        select(ToolEmbedding)
        .order_by(ToolEmbedding.server_name.nullsfirst(), ToolEmbedding.tool_name)
    )).scalars().all()

    return [_to_out(r) for r in rows]


@router.get("/tools/{tool_id}", response_model=ToolOut)
async def admin_get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
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
    return _to_out(row)


@router.post("/tools/{tool_name}/execute", response_model=ToolExecuteResponse)
async def admin_execute_tool(
    tool_name: str,
    body: ToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
    auth: Union[ApiKeyAuth, Any] = Depends(verify_auth_or_user),
):
    """Execute a local tool directly with the given arguments.

    Only local (Python) tools are supported — MCP and client tools cannot be
    executed through this endpoint.  Returns the raw tool result as JSON.

    Bot-scoped API keys are restricted to the bot's configured local_tools
    (including tools provided by carapaces).  Admin keys have unrestricted access.
    """
    from app.tools.registry import is_local_tool, call_local_tool

    if not is_local_tool(tool_name):
        raise HTTPException(status_code=404, detail=f"Local tool '{tool_name}' not found")

    # Enforce bot-level tool permissions for scoped API keys
    if isinstance(auth, ApiKeyAuth) and not has_scope(auth.scopes, "admin"):
        if not has_scope(auth.scopes, "tools:execute"):
            raise HTTPException(status_code=403, detail="Missing tools:execute scope")
        allowed = await _resolve_bot_tools(db, auth.key_id)
        if allowed is not None and tool_name not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Bot does not have access to tool '{tool_name}'",
            )

    args_json = json.dumps(body.arguments)
    logger.info("Direct tool execute: %s args=%s", tool_name, args_json[:200])
    raw = await call_local_tool(tool_name, args_json)

    # Try to parse as JSON for structured output
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "error" in parsed:
            return ToolExecuteResponse(tool_name=tool_name, result=parsed, error=parsed["error"])
        return ToolExecuteResponse(tool_name=tool_name, result=parsed)
    except (json.JSONDecodeError, TypeError):
        return ToolExecuteResponse(tool_name=tool_name, result=raw)


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

    # Add tools from carapaces
    if bot.carapaces:
        try:
            from app.agent.carapaces import resolve_carapaces
            resolved = resolve_carapaces(list(bot.carapaces))
            allowed.update(resolved.local_tools)
            allowed.update(resolved.pinned_tools)
        except Exception:
            logger.warning("Failed to resolve carapace tools for bot %s", bot_id)

    return allowed


def _to_out(row: ToolEmbedding) -> ToolOut:
    schema = row.schema_ or {}
    fn = schema.get("function", {})
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
    )
