"""Agent capability manifest endpoint."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ApiKeyAuth, get_db, require_scopes
from app.services.agent_capabilities import (
    build_agent_capability_manifest,
    preflight_agent_repair_action,
    request_agent_repair_action,
)

router = APIRouter(prefix="/agent-capabilities", tags=["agent-capabilities"])


class AgentRepairPreflightIn(BaseModel):
    action_id: str = Field(..., min_length=1)
    bot_id: str | None = None
    channel_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None


class AgentRepairRequestIn(BaseModel):
    action_id: str = Field(..., min_length=1)
    bot_id: str | None = None
    channel_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    rationale: str | None = None


def _auth_scopes(auth: Any) -> list[str] | None:
    if isinstance(auth, ApiKeyAuth):
        return list(auth.scopes)
    resolved_scopes = getattr(auth, "_resolved_scopes", None)
    return list(resolved_scopes) if resolved_scopes is not None else None


def _auth_actor(auth: Any) -> dict[str, Any]:
    if isinstance(auth, ApiKeyAuth):
        return {"kind": "api_key", "name": auth.name, "key_id": str(auth.key_id)}
    return {"kind": "user_or_admin"}


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
    # JWT users with provisioned scoped keys should see the same filtered API
    # surface that require_scopes() just authorized against. Admin JWTs have no
    # resolved scope list and intentionally inspect as the current bot context.
    scopes = _auth_scopes(auth)
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


@router.post("/actions/preflight")
async def preflight_agent_capability_action(
    payload: AgentRepairPreflightIn,
    db: AsyncSession = Depends(get_db),
    auth: Any = Depends(require_scopes("tools:read")),
) -> dict[str, Any]:
    """Dry-run a proposed Agent Readiness action before applying it."""
    return await preflight_agent_repair_action(
        db,
        action_id=payload.action_id,
        bot_id=payload.bot_id,
        channel_id=payload.channel_id,
        session_id=payload.session_id,
        actor_scopes=_auth_scopes(auth),
    )


@router.post("/actions/request")
async def request_agent_capability_action(
    payload: AgentRepairRequestIn,
    db: AsyncSession = Depends(get_db),
    auth: Any = Depends(require_scopes("tools:execute")),
) -> dict[str, Any]:
    """Queue an Agent Readiness action for human review without applying it."""
    return await request_agent_repair_action(
        db,
        action_id=payload.action_id,
        bot_id=payload.bot_id,
        channel_id=payload.channel_id,
        session_id=payload.session_id,
        requester_scopes=_auth_scopes(auth),
        actor=_auth_actor(auth),
        rationale=payload.rationale,
    )
