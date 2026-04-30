"""Agent status snapshot endpoint."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.agent_status import build_agent_status_snapshot

router = APIRouter(prefix="/agent-status", tags=["agent-status"])


class AgentStatusContext(BaseModel):
    bot_id: str | None = None
    channel_id: str | None = None
    session_id: str | None = None


class AgentStatusTrace(BaseModel):
    correlation_id: str | None = None


class AgentStatusError(BaseModel):
    message: str | None = None
    error_code: str | None = None
    error_kind: str | None = None
    retryable: bool | None = None


class AgentStatusCurrent(BaseModel):
    type: str
    id: str
    task_id: str | None = None
    heartbeat_id: str | None = None
    task_type: str | None = None
    channel_id: str | None = None
    session_id: str | None = None
    status: str
    started_at: str | None = None
    elapsed_seconds: int | None = None
    max_run_seconds: int | None = None
    stale: bool = False
    summary: str | None = None
    trace: AgentStatusTrace = Field(default_factory=AgentStatusTrace)


class AgentHeartbeatStatus(BaseModel):
    configured: bool = False
    configured_count: int | None = None
    enabled: bool = False
    heartbeat_id: str | None = None
    channel_id: str | None = None
    interval_minutes: int | None = None
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    repetition_detected: bool | None = None
    run_count: int | None = None
    max_run_seconds: int | None = None


class AgentRecentRun(BaseModel):
    type: str
    id: str
    task_id: str | None = None
    heartbeat_id: str | None = None
    task_type: str | None = None
    channel_id: str | None = None
    session_id: str | None = None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    summary: str | None = None
    trace: AgentStatusTrace = Field(default_factory=AgentStatusTrace)
    error: AgentStatusError = Field(default_factory=AgentStatusError)
    repetition_detected: bool | None = None


class AgentStatusSnapshot(BaseModel):
    schema_version: str
    available: bool
    context: AgentStatusContext
    state: str
    recommendation: str
    reason: str | None = None
    current: AgentStatusCurrent | None = None
    heartbeat: AgentHeartbeatStatus
    recent_runs: list[AgentRecentRun] = Field(default_factory=list)


@router.get("", response_model=AgentStatusSnapshot)
async def get_agent_status(
    bot_id: str | None = Query(None),
    channel_id: uuid.UUID | None = Query(None),
    session_id: uuid.UUID | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    _auth=Depends(require_scopes("logs:read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await build_agent_status_snapshot(
        db,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        limit=limit,
    )
