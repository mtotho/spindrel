"""Turns API: /turns — high-level view of agent turns for orchestrator troubleshooting."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session, ToolCall, TraceEvent
from app.dependencies import get_db, verify_auth_or_user
from ._helpers import _parse_time, build_tool_call_previews

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TurnToolCall(BaseModel):
    tool_name: str
    tool_type: str
    iteration: Optional[int] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    arguments_preview: Optional[str] = None
    result_preview: Optional[str] = None


class TurnError(BaseModel):
    event_name: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[str] = None


class TurnSummary(BaseModel):
    correlation_id: str
    created_at: str
    bot_id: Optional[str] = None
    model: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    session_id: Optional[str] = None
    # Content
    user_message: Optional[str] = None
    response_preview: Optional[str] = None
    # Metrics
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    iterations: int = 0
    duration_ms: Optional[int] = None
    llm_duration_ms: int = 0
    # Status
    has_error: bool = False
    tool_call_count: int = 0
    tool_calls: list[TurnToolCall] = []
    errors: list[TurnError] = []


class TurnsListOut(BaseModel):
    turns: list[TurnSummary]
    total: int
    count: int


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/turns", response_model=TurnsListOut)
async def list_turns(
    count: int = Query(20, ge=1, le=200, description="Number of turns to return"),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID"),
    bot_id: Optional[str] = Query(None, description="Filter by bot ID"),
    after: Optional[str] = Query(None, description="Only turns after this ISO timestamp or relative like '30m', '2h', '1d'"),
    before: Optional[str] = Query(None, description="Only turns before this ISO timestamp"),
    has_error: Optional[bool] = Query(None, description="Filter to turns with/without errors"),
    has_tool_calls: Optional[bool] = Query(None, description="Filter to turns with/without tool calls"),
    search: Optional[str] = Query(None, description="Search in user message text"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """List recent agent turns with tool calls, token usage, errors, and timing.

    Each turn is identified by a correlation_id. Returns turns newest-first
    with nested tool call details and error info.

    Designed for orchestrator agents to troubleshoot bot activity across channels.
    """
    # -----------------------------------------------------------------------
    # Step 1: Find distinct correlation_ids from user messages (each = one turn)
    # -----------------------------------------------------------------------
    msg_q = (
        select(
            Message.correlation_id,
            Message.session_id,
            Message.content,
            Message.created_at,
        )
        .where(Message.role == "user")
        .where(Message.correlation_id.is_not(None))
        .order_by(Message.created_at.desc())
    )

    # Session subquery for channel filtering
    if channel_id:
        try:
            cid = uuid.UUID(channel_id)
            session_sub = select(Session.id).where(Session.channel_id == cid)
            msg_q = msg_q.where(Message.session_id.in_(session_sub))
        except ValueError:
            return TurnsListOut(turns=[], total=0, count=0)

    # Time filters
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None
    if after_dt:
        msg_q = msg_q.where(Message.created_at >= after_dt)
    if before_dt:
        msg_q = msg_q.where(Message.created_at <= before_dt)

    if search:
        msg_q = msg_q.where(Message.content.ilike(f"%{search}%"))

    # Grab more than needed so we can post-filter
    _fetch_limit = count * 3 if (has_error is not None or has_tool_calls is not None) else count
    msg_q = msg_q.limit(min(_fetch_limit, 600))

    user_msgs = (await db.execute(msg_q)).all()
    if not user_msgs:
        return TurnsListOut(turns=[], total=0, count=0)

    correlation_ids = [r.correlation_id for r in user_msgs]
    msg_map: dict[uuid.UUID, tuple] = {r.correlation_id: r for r in user_msgs}

    # -----------------------------------------------------------------------
    # Step 2: Batch-load tool calls, trace events, and session info
    # -----------------------------------------------------------------------
    tool_calls_q = (
        select(ToolCall)
        .where(ToolCall.correlation_id.in_(correlation_ids))
        .order_by(ToolCall.created_at)
    )
    tool_calls_all = (await db.execute(tool_calls_q)).scalars().all()

    trace_q = (
        select(TraceEvent)
        .where(TraceEvent.correlation_id.in_(correlation_ids))
        .where(TraceEvent.event_type.in_([
            "token_usage", "error", "llm_error", "response",
        ]))
        .order_by(TraceEvent.created_at)
    )
    trace_events_all = (await db.execute(trace_q)).scalars().all()

    # Session → channel mapping
    session_ids = list({r.session_id for r in user_msgs if r.session_id})
    session_channel_map: dict[uuid.UUID, tuple[uuid.UUID | None, str | None, str | None]] = {}
    if session_ids:
        sess_q = (
            select(Session.id, Session.channel_id, Session.bot_id)
            .where(Session.id.in_(session_ids))
        )
        for row in (await db.execute(sess_q)).all():
            session_channel_map[row.id] = (row.channel_id, None, row.bot_id)

    # Channel names
    ch_ids = list({v[0] for v in session_channel_map.values() if v[0]})
    channel_name_map: dict[uuid.UUID, str] = {}
    if ch_ids:
        ch_q = select(Channel.id, Channel.name).where(Channel.id.in_(ch_ids))
        for row in (await db.execute(ch_q)).all():
            channel_name_map[row.id] = row.name

    # -----------------------------------------------------------------------
    # Step 3: Group by correlation_id and build TurnSummary objects
    # -----------------------------------------------------------------------
    tc_by_corr: dict[uuid.UUID, list[ToolCall]] = {}
    for tc in tool_calls_all:
        tc_by_corr.setdefault(tc.correlation_id, []).append(tc)

    te_by_corr: dict[uuid.UUID, list[TraceEvent]] = {}
    for te in trace_events_all:
        te_by_corr.setdefault(te.correlation_id, []).append(te)

    turns: list[TurnSummary] = []
    for cid in correlation_ids:
        msg_row = msg_map[cid]
        tcs = tc_by_corr.get(cid, [])
        tes = te_by_corr.get(cid, [])

        # Token totals + model from token_usage events
        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        llm_duration_ms = 0
        model = None
        iterations = 0
        for te in tes:
            if te.event_type == "token_usage" and te.data:
                total_tokens += te.data.get("total_tokens", 0)
                prompt_tokens += te.data.get("prompt_tokens", 0)
                completion_tokens += te.data.get("completion_tokens", 0)
                iterations = max(iterations, te.data.get("iteration", 0))
                if te.data.get("model"):
                    model = te.data["model"]
                if te.duration_ms:
                    llm_duration_ms += te.duration_ms

        # Errors
        errors: list[TurnError] = []
        for te in tes:
            if te.event_type in ("error", "llm_error"):
                error_msg = None
                if te.data:
                    error_msg = te.data.get("traceback", te.data.get("error", ""))
                    if error_msg and len(error_msg) > 500:
                        error_msg = error_msg[:500] + "..."
                errors.append(TurnError(
                    event_name=te.event_name,
                    message=error_msg,
                    created_at=te.created_at.isoformat() if te.created_at else None,
                ))

        # Response preview
        response_preview = None
        for te in tes:
            if te.event_type == "response" and te.data:
                response_preview = te.data.get("text", "")
                if response_preview and len(response_preview) > 300:
                    response_preview = response_preview[:300] + "..."

        # Tool calls
        turn_tool_calls = [TurnToolCall(**d) for d in build_tool_call_previews(tcs)]

        has_err = len(errors) > 0 or any(tc.error for tc in tcs)

        # Post-filters
        if has_error is True and not has_err:
            continue
        if has_error is False and has_err:
            continue
        if has_tool_calls is True and not turn_tool_calls:
            continue
        if has_tool_calls is False and turn_tool_calls:
            continue

        # Bot ID from session or trace events
        sess_info = session_channel_map.get(msg_row.session_id)
        turn_bot_id = sess_info[2] if sess_info else None
        if not turn_bot_id:
            # Fallback: get from trace events
            for te in tes:
                if te.bot_id:
                    turn_bot_id = te.bot_id
                    break

        # Bot ID filter (applied here because we derive it from session)
        if bot_id and turn_bot_id != bot_id:
            continue

        ch_id = sess_info[0] if sess_info else None
        ch_name = channel_name_map.get(ch_id) if ch_id else None

        # Duration: first user message → last trace event or tool call
        turn_duration_ms = None
        all_timestamps = [msg_row.created_at]
        for tc in tcs:
            if tc.created_at:
                all_timestamps.append(tc.created_at)
        for te in tes:
            if te.created_at:
                all_timestamps.append(te.created_at)
        if len(all_timestamps) > 1:
            turn_duration_ms = int((max(all_timestamps) - min(all_timestamps)).total_seconds() * 1000)

        user_msg_preview = msg_row.content
        if user_msg_preview and len(user_msg_preview) > 300:
            user_msg_preview = user_msg_preview[:300] + "..."

        turns.append(TurnSummary(
            correlation_id=str(cid),
            created_at=msg_row.created_at.isoformat(),
            bot_id=turn_bot_id,
            model=model,
            channel_id=str(ch_id) if ch_id else None,
            channel_name=ch_name,
            session_id=str(msg_row.session_id) if msg_row.session_id else None,
            user_message=user_msg_preview,
            response_preview=response_preview,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            iterations=iterations,
            duration_ms=turn_duration_ms,
            llm_duration_ms=llm_duration_ms,
            has_error=has_err,
            tool_call_count=len(turn_tool_calls),
            tool_calls=turn_tool_calls,
            errors=errors,
        ))

        if len(turns) >= count:
            break

    return TurnsListOut(
        turns=turns,
        total=len(turns),
        count=count,
    )


