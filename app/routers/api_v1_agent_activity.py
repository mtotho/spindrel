"""Agent activity replay endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.agent_activity import AGENT_ACTIVITY_KINDS, list_agent_activity

router = APIRouter(prefix="/agent-activity", tags=["agent-activity"])


class AgentActivityActor(BaseModel):
    bot_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None


class AgentActivityTarget(BaseModel):
    channel_id: str | None = None
    project_id: str | None = None
    widget_pin_ids: list[str] = Field(default_factory=list)


class AgentActivityTrace(BaseModel):
    correlation_id: str | None = None
    tool_call_id: str | None = None


class AgentActivityError(BaseModel):
    error_code: str | None = None
    error_kind: str | None = None
    retryable: bool | None = None


class AgentActivityItem(BaseModel):
    id: str
    kind: str
    actor: AgentActivityActor
    target: AgentActivityTarget
    status: str
    summary: str
    next_action: str | None = None
    trace: AgentActivityTrace
    error: AgentActivityError
    created_at: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


@router.get("", response_model=list[AgentActivityItem])
async def get_agent_activity(
    bot_id: str | None = Query(None),
    channel_id: uuid.UUID | None = Query(None),
    session_id: uuid.UUID | None = Query(None),
    task_id: uuid.UUID | None = Query(None),
    correlation_id: uuid.UUID | None = Query(None),
    kind: str | None = Query(None, pattern=f"^({'|'.join(AGENT_ACTIVITY_KINDS)})$"),
    since: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _auth=Depends(require_scopes("logs:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    return await list_agent_activity(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        task_id=task_id,
        correlation_id=correlation_id,
        kind=kind,
        since=since,
        limit=limit,
    )
