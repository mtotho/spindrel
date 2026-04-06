"""Logs & Traces: /logs, /traces/{id}, /server-logs, /log-level."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, literal, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, HeartbeatRun, Message, Session, Task, ToolCall, TraceEvent
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
    """List log entries (tool calls + trace events), merged and sorted desc.

    Uses DB-side UNION ALL with ORDER BY / LIMIT / OFFSET for proper
    pagination regardless of dataset size.
    """
    pg_offset = (page - 1) * page_size

    # Build common filter conditions for both tables
    tc_filters = []
    te_filters = []
    if bot_id:
        tc_filters.append(ToolCall.bot_id == bot_id)
        te_filters.append(TraceEvent.bot_id == bot_id)
    if session_id:
        try:
            sid = uuid.UUID(session_id)
            tc_filters.append(ToolCall.session_id == sid)
            te_filters.append(TraceEvent.session_id == sid)
        except ValueError:
            pass
    if channel_id:
        try:
            cid = uuid.UUID(channel_id)
            session_sub = select(Session.id).where(Session.channel_id == cid)
            tc_filters.append(ToolCall.session_id.in_(session_sub))
            te_filters.append(TraceEvent.session_id.in_(session_sub))
        except ValueError:
            pass

    # event_type filter: "tool_call" shows only tool calls, anything else
    # shows only trace events matching that type
    skip_tc = event_type is not None and event_type != "tool_call"
    skip_te = event_type == "tool_call"
    if event_type and event_type != "tool_call":
        te_filters.append(TraceEvent.event_type == event_type)

    # Tool calls subquery — project shared columns for UNION ALL
    tc_q = (
        select(
            ToolCall.id,
            ToolCall.created_at,
            literal("tool_call").label("kind"),
            ToolCall.correlation_id,
            ToolCall.session_id,
            ToolCall.bot_id,
            ToolCall.client_id,
            ToolCall.tool_name,
            ToolCall.tool_type,
            ToolCall.arguments,
            ToolCall.result,
            ToolCall.error,
            ToolCall.duration_ms,
            literal(None).label("event_type"),
            literal(None).label("event_name"),
            literal(None).label("count"),
            literal(None).label("data"),
        )
        .where(*tc_filters)
    )

    # Trace events subquery
    te_q = (
        select(
            TraceEvent.id,
            TraceEvent.created_at,
            literal("trace_event").label("kind"),
            TraceEvent.correlation_id,
            TraceEvent.session_id,
            TraceEvent.bot_id,
            TraceEvent.client_id,
            literal(None).label("tool_name"),
            literal(None).label("tool_type"),
            literal(None).label("arguments"),
            literal(None).label("result"),
            literal(None).label("error"),
            TraceEvent.duration_ms,
            TraceEvent.event_type,
            TraceEvent.event_name,
            TraceEvent.count,
            TraceEvent.data,
        )
        .where(*te_filters)
    )

    # Build the UNION ALL (or single source if one side is filtered out)
    if skip_tc and skip_te:
        # Contradictory filters — return empty
        return LogListOut(rows=[], total=0, page=page, page_size=page_size, bot_ids=[])
    elif skip_tc:
        combined = te_q.subquery()
    elif skip_te:
        combined = tc_q.subquery()
    else:
        combined = union_all(tc_q, te_q).subquery()

    count_stmt = select(func.count()).select_from(combined)
    data_stmt = (
        select(combined)
        .order_by(combined.c.created_at.desc())
        .limit(page_size)
        .offset(pg_offset)
    )

    total_result = await db.execute(count_stmt)
    data_result = await db.execute(data_stmt)
    total = total_result.scalar() or 0
    raw_rows = data_result.all()

    bot_ids_result = (await db.execute(select(ToolCall.bot_id).distinct())).scalars().all()

    rows: list[LogRow] = []
    for r in raw_rows:
        result_text = r.result
        if result_text and len(result_text) > 500:
            result_text = result_text[:500] + "..."
        rows.append(LogRow(
            kind=r.kind,
            id=str(r.id),
            created_at=r.created_at.isoformat() if r.created_at else None,
            correlation_id=str(r.correlation_id) if r.correlation_id else None,
            session_id=str(r.session_id) if r.session_id else None,
            bot_id=r.bot_id,
            client_id=r.client_id,
            tool_name=r.tool_name,
            tool_type=r.tool_type,
            arguments=r.arguments if r.kind == "tool_call" else None,
            result=result_text if r.kind == "tool_call" else None,
            error=r.error if r.kind == "tool_call" else None,
            duration_ms=r.duration_ms,
            event_type=r.event_type if r.kind == "trace_event" else None,
            event_name=r.event_name if r.kind == "trace_event" else None,
            count=r.count if r.kind == "trace_event" else None,
            data=r.data if r.kind == "trace_event" else None,
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

    from app.services.secret_registry import redact as _redact_secrets

    events: list[TraceEventOut] = []
    for item in merged:
        obj = item["obj"]
        if item["kind"] == "tool_call":
            events.append(TraceEventOut(
                kind="tool_call",
                tool_name=obj.tool_name,
                tool_type=obj.tool_type,
                arguments=obj.arguments,
                result=_redact_secrets(obj.result) if obj.result else obj.result,
                error=_redact_secrets(obj.error) if obj.error else obj.error,
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
            # Redact known secrets from message content in traces
            from app.services.secret_registry import redact as _redact_secrets
            content = _redact_secrets(content)
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
# Traces list — all correlation_ids across the system
# ---------------------------------------------------------------------------

class TraceSummary(BaseModel):
    correlation_id: str
    source_type: str  # agent, heartbeat, task, workflow
    bot_id: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    task_type: Optional[str] = None
    title: Optional[str] = None
    has_error: bool = False
    tool_call_count: int = 0
    total_tokens: int = 0
    duration_ms: Optional[int] = None
    created_at: str


class TracesListOut(BaseModel):
    traces: list[TraceSummary]
    has_more: bool = False


@router.get("/traces", response_model=TracesListOut)
async def list_traces(
    count: int = Query(50, ge=1, le=200),
    bot_id: Optional[str] = None,
    source_type: Optional[str] = None,
    before: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("logs:read")),
):
    """List recent traces from all sources (agent turns, tasks, heartbeats, workflows).

    Each trace is a distinct correlation_id with summary metadata.
    Click through to /traces/{correlation_id} for the full timeline.
    """
    from app.routers.api_v1_admin._helpers import _parse_time

    # -----------------------------------------------------------------------
    # Step 1: Gather distinct correlation_ids from relevant sources
    # Pre-filter by source_type to skip irrelevant queries
    # -----------------------------------------------------------------------
    from app.db.models import ChannelHeartbeat

    # Determine which sources to query
    want_tasks = source_type in (None, "task", "workflow")
    want_heartbeats = source_type in (None, "heartbeat")
    want_agents = source_type in (None, "agent")
    fetch_limit = count * 3

    tasks_result = []
    hb_result = []
    msg_result = []

    if want_tasks:
        task_q = (
            select(
                Task.correlation_id,
                Task.bot_id,
                Task.channel_id,
                Task.task_type,
                Task.title,
                Task.prompt,
                Task.status,
                Task.run_at,
                Task.created_at,
            )
            .where(Task.correlation_id.is_not(None))
            .order_by(Task.created_at.desc())
            .limit(fetch_limit)
        )
        if bot_id:
            task_q = task_q.where(Task.bot_id == bot_id)
        if source_type == "workflow":
            task_q = task_q.where(Task.task_type == "workflow")
        elif source_type == "task":
            task_q = task_q.where(Task.task_type != "workflow")
        if before:
            before_dt = _parse_time(before)
            if before_dt:
                task_q = task_q.where(Task.created_at < before_dt)
        tasks_result = (await db.execute(task_q)).all()

    if want_heartbeats:
        hb_q = (
            select(
                HeartbeatRun.correlation_id,
                Channel.bot_id.label("bot_id"),
                ChannelHeartbeat.channel_id,
                HeartbeatRun.run_at,
                HeartbeatRun.status,
            )
            .join(ChannelHeartbeat, HeartbeatRun.heartbeat_id == ChannelHeartbeat.id)
            .join(Channel, ChannelHeartbeat.channel_id == Channel.id)
            .where(HeartbeatRun.correlation_id.is_not(None))
            .order_by(HeartbeatRun.run_at.desc())
            .limit(fetch_limit)
        )
        if bot_id:
            from app.services.channels import bot_channel_filter
            hb_q = hb_q.where(bot_channel_filter(bot_id))
        if before:
            before_dt = _parse_time(before)
            if before_dt:
                hb_q = hb_q.where(HeartbeatRun.run_at < before_dt)
        hb_result = (await db.execute(hb_q)).all()

    if want_agents:
        msg_q = (
            select(
                Message.correlation_id,
                Message.session_id,
                Message.created_at,
            )
            .where(Message.role == "user")
            .where(Message.correlation_id.is_not(None))
            .order_by(Message.created_at.desc())
            .limit(fetch_limit)
        )
        if before:
            before_dt = _parse_time(before)
            if before_dt:
                msg_q = msg_q.where(Message.created_at < before_dt)
        msg_result = (await db.execute(msg_q)).all()

    # -----------------------------------------------------------------------
    # Step 2: Build unified list, deduplicating by correlation_id
    # -----------------------------------------------------------------------
    seen: dict[uuid.UUID, dict] = {}

    # Tasks first — they have the most metadata
    for r in tasks_result:
        if r.correlation_id in seen:
            continue
        st = "workflow" if r.task_type == "workflow" else "task"
        if r.task_type == "heartbeat":
            st = "heartbeat"
        title = r.title
        if not title and r.prompt:
            title = r.prompt[:80] + ("..." if len(r.prompt) > 80 else "")
        seen[r.correlation_id] = {
            "correlation_id": str(r.correlation_id),
            "source_type": st,
            "bot_id": r.bot_id,
            "channel_id": str(r.channel_id) if r.channel_id else None,
            "task_type": r.task_type,
            "title": title,
            "has_error": r.status == "failed",
            "created_at": (r.run_at or r.created_at).isoformat(),
        }

    # Heartbeats
    for r in hb_result:
        if r.correlation_id in seen:
            continue
        seen[r.correlation_id] = {
            "correlation_id": str(r.correlation_id),
            "source_type": "heartbeat",
            "bot_id": r.bot_id,
            "channel_id": str(r.channel_id) if r.channel_id else None,
            "task_type": None,
            "title": None,
            "has_error": r.status == "failed",
            "created_at": r.run_at.isoformat() if r.run_at else None,
        }

    # Agent chat turns (from user messages) — only if not already covered
    # Resolve session → bot/channel
    session_ids = list({r.session_id for r in msg_result if r.session_id and r.correlation_id not in seen})
    sess_map: dict[uuid.UUID, tuple] = {}
    if session_ids:
        sess_rows = (await db.execute(
            select(Session.id, Session.bot_id, Session.channel_id)
            .where(Session.id.in_(session_ids))
        )).all()
        sess_map = {r.id: (r.bot_id, r.channel_id) for r in sess_rows}

    for r in msg_result:
        if r.correlation_id in seen:
            continue
        sess_info = sess_map.get(r.session_id, (None, None))
        msg_bot_id = sess_info[0]
        if bot_id and msg_bot_id != bot_id:
            continue
        seen[r.correlation_id] = {
            "correlation_id": str(r.correlation_id),
            "source_type": "agent",
            "bot_id": msg_bot_id,
            "channel_id": str(sess_info[1]) if sess_info[1] else None,
            "task_type": None,
            "title": None,
            "has_error": False,
            "created_at": r.created_at.isoformat(),
        }

    # -----------------------------------------------------------------------
    # Step 3: Sort by created_at desc, take top N+1 to detect has_more
    # -----------------------------------------------------------------------
    all_traces = sorted(seen.values(), key=lambda x: x.get("created_at") or "", reverse=True)
    has_more = len(all_traces) > count
    traces = all_traces[:count]

    if not traces:
        return TracesListOut(traces=[], has_more=False)

    # -----------------------------------------------------------------------
    # Step 4: Enrich with tool call counts, token usage, duration
    # -----------------------------------------------------------------------
    corr_ids = [uuid.UUID(t["correlation_id"]) for t in traces]

    # Tool call counts per correlation_id
    tc_counts = (await db.execute(
        select(ToolCall.correlation_id, func.count())
        .where(ToolCall.correlation_id.in_(corr_ids))
        .group_by(ToolCall.correlation_id)
    )).all()
    tc_count_map = {r[0]: r[1] for r in tc_counts}

    # Token usage + timing from trace_events (aggregate in Python like turns endpoint)
    token_events = (await db.execute(
        select(TraceEvent.correlation_id, TraceEvent.data, TraceEvent.created_at)
        .where(TraceEvent.correlation_id.in_(corr_ids))
        .where(TraceEvent.event_type == "token_usage")
    )).all()
    token_map: dict[uuid.UUID, tuple] = {}  # cid -> (total_tokens, first_at, last_at)
    for r in token_events:
        tokens = (r.data or {}).get("total_tokens", 0)
        prev = token_map.get(r.correlation_id, (0, r.created_at, r.created_at))
        token_map[r.correlation_id] = (
            prev[0] + (tokens or 0),
            min(prev[1], r.created_at) if prev[1] else r.created_at,
            max(prev[2], r.created_at) if prev[2] else r.created_at,
        )

    # Error detection from trace_events
    error_corrs = set()
    error_rows = (await db.execute(
        select(TraceEvent.correlation_id)
        .where(TraceEvent.correlation_id.in_(corr_ids))
        .where(TraceEvent.event_type.in_(["error", "llm_error"]))
        .distinct()
    )).scalars().all()
    error_corrs = set(error_rows)

    # Channel names
    ch_ids = list({uuid.UUID(t["channel_id"]) for t in traces if t.get("channel_id")})
    ch_name_map: dict[str, str] = {}
    if ch_ids:
        ch_rows = (await db.execute(
            select(Channel.id, Channel.name).where(Channel.id.in_(ch_ids))
        )).all()
        ch_name_map = {str(r.id): r.name for r in ch_rows}

    # -----------------------------------------------------------------------
    # Step 5: Assemble final output
    # -----------------------------------------------------------------------
    result: list[TraceSummary] = []
    for t in traces:
        cid = uuid.UUID(t["correlation_id"])
        token_info = token_map.get(cid, (0, None, None))
        duration_ms = None
        if token_info[1] and token_info[2]:
            duration_ms = int((token_info[2] - token_info[1]).total_seconds() * 1000)

        result.append(TraceSummary(
            correlation_id=t["correlation_id"],
            source_type=t["source_type"],
            bot_id=t["bot_id"],
            channel_id=t["channel_id"],
            channel_name=ch_name_map.get(t["channel_id"] or ""),
            task_type=t["task_type"],
            title=t["title"],
            has_error=t["has_error"] or cid in error_corrs,
            tool_call_count=tc_count_map.get(cid, 0),
            total_tokens=token_info[0],
            duration_ms=duration_ms,
            created_at=t["created_at"],
        ))

    return TracesListOut(traces=result, has_more=has_more)


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
