"""Logs & Traces: /logs, /traces/{id}, /server-logs, /log-level."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Session, ToolCall, TraceEvent
from app.dependencies import get_db, require_scopes

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LogRow(BaseModel):
    kind: str
    id: str
    created_at: Optional[str] = None
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None
    bot_id: Optional[str] = None
    client_id: Optional[str] = None
    # tool_call fields
    tool_name: Optional[str] = None
    tool_type: Optional[str] = None
    arguments: Optional[dict] = None
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    # trace_event fields
    event_type: Optional[str] = None
    event_name: Optional[str] = None
    count: Optional[int] = None
    data: Optional[dict] = None


class LogListOut(BaseModel):
    rows: list[LogRow]
    total: int
    page: int
    page_size: int
    bot_ids: list[str]


class TraceEventOut(BaseModel):
    kind: str
    created_at: Optional[str] = None
    # tool_call
    tool_name: Optional[str] = None
    tool_type: Optional[str] = None
    arguments: Optional[dict] = None
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    # trace_event
    event_type: Optional[str] = None
    event_name: Optional[str] = None
    count: Optional[int] = None
    data: Optional[dict] = None
    # message
    role: Optional[str] = None
    content: Optional[str] = None


class TraceDetailOut(BaseModel):
    events: list[TraceEventOut]
    correlation_id: str
    session_id: Optional[str] = None
    bot_id: Optional[str] = None
    client_id: Optional[str] = None
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/logs", response_model=LogListOut)
async def admin_logs(
    event_type: Optional[str] = None,
    bot_id: Optional[str] = None,
    session_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("logs:read")),
):
    """List log entries (tool calls + trace events), merged and sorted desc."""
    offset = (page - 1) * page_size

    tc_stmt = select(ToolCall).order_by(ToolCall.created_at.desc())
    te_stmt = select(TraceEvent).order_by(TraceEvent.created_at.desc())

    if bot_id:
        tc_stmt = tc_stmt.where(ToolCall.bot_id == bot_id)
        te_stmt = te_stmt.where(TraceEvent.bot_id == bot_id)

    if session_id:
        try:
            sid = uuid.UUID(session_id)
            tc_stmt = tc_stmt.where(ToolCall.session_id == sid)
            te_stmt = te_stmt.where(TraceEvent.session_id == sid)
        except ValueError:
            pass

    if channel_id:
        try:
            cid = uuid.UUID(channel_id)
            session_sub = select(Session.id).where(Session.channel_id == cid)
            tc_stmt = tc_stmt.where(ToolCall.session_id.in_(session_sub))
            te_stmt = te_stmt.where(TraceEvent.session_id.in_(session_sub))
        except ValueError:
            pass

    if event_type == "tool_call":
        te_stmt = te_stmt.where(text("false"))
    elif event_type and event_type != "tool_call":
        tc_stmt = tc_stmt.where(text("false"))
        te_stmt = te_stmt.where(TraceEvent.event_type == event_type)

    tool_calls = (await db.execute(tc_stmt.limit(500))).scalars().all()
    trace_events = (await db.execute(te_stmt.limit(500))).scalars().all()

    merged: list[dict] = []
    for tc in tool_calls:
        merged.append({"kind": "tool_call", "obj": tc, "created_at": tc.created_at})
    for te in trace_events:
        merged.append({"kind": "trace_event", "obj": te, "created_at": te.created_at})
    merged.sort(key=lambda x: x["created_at"], reverse=True)

    total = len(merged)
    page_items = merged[offset: offset + page_size]

    bot_ids_result = (await db.execute(select(ToolCall.bot_id).distinct())).scalars().all()

    rows: list[LogRow] = []
    for item in page_items:
        obj = item["obj"]
        if item["kind"] == "tool_call":
            result_text = obj.result
            if result_text and len(result_text) > 500:
                result_text = result_text[:500] + "..."
            rows.append(LogRow(
                kind="tool_call",
                id=str(obj.id),
                created_at=obj.created_at.isoformat() if obj.created_at else None,
                correlation_id=str(obj.correlation_id) if obj.correlation_id else None,
                session_id=str(obj.session_id) if obj.session_id else None,
                bot_id=obj.bot_id,
                client_id=obj.client_id,
                tool_name=obj.tool_name,
                tool_type=obj.tool_type,
                arguments=obj.arguments,
                result=result_text,
                error=obj.error,
                duration_ms=obj.duration_ms,
            ))
        else:
            rows.append(LogRow(
                kind="trace_event",
                id=str(obj.id),
                created_at=obj.created_at.isoformat() if obj.created_at else None,
                correlation_id=str(obj.correlation_id) if obj.correlation_id else None,
                session_id=str(obj.session_id) if obj.session_id else None,
                bot_id=obj.bot_id,
                client_id=obj.client_id,
                event_type=obj.event_type,
                event_name=obj.event_name,
                count=obj.count,
                data=obj.data,
                duration_ms=obj.duration_ms,
            ))

    return LogListOut(
        rows=rows,
        total=total,
        page=page,
        page_size=page_size,
        bot_ids=sorted(filter(None, bot_ids_result)),
    )


@router.get("/traces/{correlation_id}", response_model=TraceDetailOut)
async def admin_trace_detail(
    correlation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("logs:read")),
):
    """Get full trace timeline for a correlation ID."""
    tool_calls = (await db.execute(
        select(ToolCall)
        .where(ToolCall.correlation_id == correlation_id)
        .order_by(ToolCall.created_at)
    )).scalars().all()

    trace_events = (await db.execute(
        select(TraceEvent)
        .where(TraceEvent.correlation_id == correlation_id)
        .order_by(TraceEvent.created_at)
    )).scalars().all()

    messages = (await db.execute(
        select(Message)
        .where(Message.correlation_id == correlation_id)
        .where(Message.role.in_(["user", "assistant"]))
        .order_by(Message.created_at)
    )).scalars().all()

    merged: list[dict] = []
    for tc in tool_calls:
        merged.append({"kind": "tool_call", "obj": tc, "created_at": tc.created_at})
    for te in trace_events:
        merged.append({"kind": "trace_event", "obj": te, "created_at": te.created_at})
    for msg in messages:
        if msg.role == "user" or (msg.role == "assistant" and msg.content):
            merged.append({"kind": "message", "obj": msg, "created_at": msg.created_at})
    merged.sort(key=lambda x: x["created_at"])

    session_id = None
    bot_id = None
    client_id = None
    for item in merged:
        obj = item["obj"]
        if hasattr(obj, "session_id") and obj.session_id:
            session_id = str(obj.session_id)
        if hasattr(obj, "bot_id") and obj.bot_id:
            bot_id = obj.bot_id
        if hasattr(obj, "client_id") and obj.client_id:
            client_id = obj.client_id
        if session_id and bot_id and client_id:
            break

    time_range_start = merged[0]["created_at"] if merged else None
    time_range_end = merged[-1]["created_at"] if merged else None

    events: list[TraceEventOut] = []
    for item in merged:
        obj = item["obj"]
        if item["kind"] == "tool_call":
            events.append(TraceEventOut(
                kind="tool_call",
                tool_name=obj.tool_name,
                tool_type=obj.tool_type,
                arguments=obj.arguments,
                result=obj.result,
                error=obj.error,
                duration_ms=obj.duration_ms,
                created_at=obj.created_at.isoformat() if obj.created_at else None,
            ))
        elif item["kind"] == "trace_event":
            events.append(TraceEventOut(
                kind="trace_event",
                event_type=obj.event_type,
                event_name=obj.event_name,
                count=obj.count,
                data=obj.data,
                duration_ms=obj.duration_ms,
                created_at=obj.created_at.isoformat() if obj.created_at else None,
            ))
        else:
            content = obj.content or ""
            if isinstance(content, str) and content.startswith("["):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        content = " ".join(
                            p.get("text", "") for p in parsed
                            if isinstance(p, dict) and p.get("type") == "text"
                        ) or "[multimodal]"
                except Exception:
                    pass
            events.append(TraceEventOut(
                kind="message",
                role=obj.role,
                content=content,
                created_at=obj.created_at.isoformat() if obj.created_at else None,
            ))

    return TraceDetailOut(
        events=events,
        correlation_id=str(correlation_id),
        session_id=session_id,
        bot_id=bot_id,
        client_id=client_id,
        time_range_start=time_range_start.isoformat() if time_range_start else None,
        time_range_end=time_range_end.isoformat() if time_range_end else None,
    )


# ---------------------------------------------------------------------------
# Server Logs (in-memory ring buffer)
# ---------------------------------------------------------------------------

class ServerLogEntry(BaseModel):
    timestamp: float
    level: str
    logger: str
    message: str
    formatted: str


class ServerLogsOut(BaseModel):
    entries: list[ServerLogEntry]
    total: int
    levels: list[str]


@router.get("/server-logs", response_model=ServerLogsOut)
async def server_logs(
    tail: int = Query(200, ge=1, le=5000, description="Number of entries to return"),
    level: Optional[str] = Query(None, description="Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
    logger: Optional[str] = Query(None, description="Logger name prefix filter (e.g. 'app.agent')"),
    search: Optional[str] = Query(None, description="Case-insensitive text search in message"),
    since_minutes: Optional[float] = Query(None, ge=0, description="Only entries from last N minutes"),
    _auth=Depends(require_scopes("logs:read")),
):
    """Return recent server log entries from the in-memory ring buffer.

    Filters:
    - **level**: minimum severity (e.g. ERROR returns ERROR + CRITICAL)
    - **logger**: prefix match on logger name (e.g. "app.agent" matches "app.agent.loop")
    - **search**: substring match in log message text
    - **since_minutes**: only entries from the last N minutes
    - **tail**: max entries to return (newest last)
    """
    from app.services.log_buffer import get_handler

    handler = get_handler()
    if handler is None:
        return ServerLogsOut(entries=[], total=0, levels=[])

    since = time.time() - (since_minutes * 60) if since_minutes else None

    entries = handler.query(
        tail=tail,
        level=level,
        logger=logger,
        search=search,
        since=since,
    )

    return ServerLogsOut(
        entries=[
            ServerLogEntry(
                timestamp=e.timestamp,
                level=e.level,
                logger=e.logger,
                message=e.message,
                formatted=e.formatted,
            )
            for e in entries
        ],
        total=len(entries),
        levels=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )


# ---------------------------------------------------------------------------
# Dynamic log level
# ---------------------------------------------------------------------------

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class LogLevelOut(BaseModel):
    level: str


class LogLevelIn(BaseModel):
    level: str


@router.get("/log-level", response_model=LogLevelOut)
async def get_log_level(
    _auth=Depends(require_scopes("logs:read")),
):
    """Return the current root logger level."""
    return LogLevelOut(level=logging.getLevelName(logging.getLogger().level))


@router.put("/log-level", response_model=LogLevelOut)
async def set_log_level(
    body: LogLevelIn,
    _auth=Depends(require_scopes("logs:write")),
):
    """Set the root logger level dynamically (DEBUG/INFO/WARNING/ERROR/CRITICAL)."""
    name = body.level.upper()
    if name not in _VALID_LEVELS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid level: {body.level}. Must be one of {sorted(_VALID_LEVELS)}")
    logging.getLogger().setLevel(getattr(logging, name))
    return LogLevelOut(level=name)
