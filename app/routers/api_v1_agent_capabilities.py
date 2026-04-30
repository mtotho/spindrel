"""Agent capability manifest endpoint."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ApiKeyAuth, get_db, require_scopes
from app.services.agent_capabilities import build_agent_capability_manifest

router = APIRouter(prefix="/agent-capabilities", tags=["agent-capabilities"])


@router.get("")
async def get_agent_capabilities(
    bot_id: str | None = Query(None),
    channel_id: uuid.UUID | None = Query(None),
    session_id: uuid.UUID | None = Query(None),
    include_schemas: bool = Query(False),
    include_endpoints: bool = Query(True),
    max_tools: int = Query(80, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    auth: Any = Depends(require_scopes("tools:read")),
) -> dict[str, Any]:
    """Return a machine-readable manifest of the agent's usable surface.

    Scoped API keys see the endpoint list filtered to their grants. Admin/JWT
    callers may pass an explicit bot/channel/session context to inspect what a
    turn would inherit.
    """
    if isinstance(auth, ApiKeyAuth):
        scopes = list(auth.scopes)
    else:
        # JWT users with provisioned scoped keys should see the same filtered
        # API surface that require_scopes() just authorized against. Admin JWTs
        # have no resolved scope list and intentionally see the full catalog.
        resolved_scopes = getattr(auth, "_resolved_scopes", None)
        scopes = list(resolved_scopes) if resolved_scopes is not None else None
    return await build_agent_capability_manifest(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        scopes=scopes,
        include_schemas=include_schemas,
        include_endpoints=include_endpoints,
        max_tools=max_tools,
    )
