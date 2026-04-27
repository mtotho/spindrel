"""Agent self-debugging tools: browse conversation traces and inspect specific turns."""
import json
import uuid

from sqlalchemy import func, select

from app.agent.context import current_correlation_id, current_session_id
from app.db.engine import async_session
from app.db.models import Message, ToolCall, TraceEvent
from app.tools.registry import register

_USER_MESSAGE_PREVIEW_CHARS = 400


@register({
    "type": "function",
    "function": {
        "name": "list_session_traces",
        "description": (
            "List recent conversation turns for the current channel, showing which had errors, "
            "how many tool calls were made, and a preview of the user's message. "
            "Use this to find a failing turn, then call get_trace with its correlation_id to inspect it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent turns to show (default 10, max 50).",
                },
            },
            "required": [],
        },
    },
}, returns={
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "traces": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "correlation_id": {"type": "string"},
                    "started_at": {"type": ["string", "null"]},
                    "tool_count": {"type": "integer"},
                    "event_count": {"type": "integer"},
                    "error_count": {"type": "integer"},
                    "user_message_preview": {"type": ["string", "null"]},
                },
                "required": ["correlation_id", "event_count"],
            },
        },
        "message": {"type": "string"},
    },
    "required": ["count"],
})
async def list_session_traces(limit: int = 10) -> str:
    session_id = current_session_id.get()
    if not session_id:
        return json.dumps({"count": 0, "traces": [], "message": "No conversation context available."}, ensure_ascii=False)

    limit = min(max(1, limit), 50)

    async with async_session() as db:
        # Get distinct correlation_ids for this session from trace_events, ordered by first event
        rows = (await db.execute(
            select(
                TraceEvent.correlation_id,
                func.min(TraceEvent.created_at).label("started_at"),
                func.count(TraceEvent.id).label("event_count"),
            )
            .where(TraceEvent.session_id == session_id)
            .group_by(TraceEvent.correlation_id)
            .order_by(func.min(TraceEvent.created_at).desc())
            .limit(limit)
        )).all()

        if not rows:
            return json.dumps({"count": 0, "traces": [], "message": "No trace events found for this conversation."}, ensure_ascii=False)

        # Collect correlation_ids to look up errors and tool call counts
        corr_ids = [r.correlation_id for r in rows]

        # Count errors per correlation_id
        error_rows = (await db.execute(
            select(TraceEvent.correlation_id, func.count(TraceEvent.id).label("n"))
            .where(
                TraceEvent.session_id == session_id,
                TraceEvent.correlation_id.in_(corr_ids),
                TraceEvent.event_type == "error",
            )
            .group_by(TraceEvent.correlation_id)
        )).all()
        error_counts = {r.correlation_id: r.n for r in error_rows}

        # Count tool calls per correlation_id
        tc_rows = (await db.execute(
            select(ToolCall.correlation_id, func.count(ToolCall.id).label("n"))
            .where(
                ToolCall.session_id == session_id,
                ToolCall.correlation_id.in_(corr_ids),
            )
            .group_by(ToolCall.correlation_id)
        )).all()
        tc_counts = {r.correlation_id: r.n for r in tc_rows}

        # Get the user message for each correlation_id
        msg_rows = (await db.execute(
            select(Message.correlation_id, Message.content)
            .where(
                Message.session_id == session_id,
                Message.correlation_id.in_(corr_ids),
                Message.role == "user",
            )
            .order_by(Message.created_at)
        )).all()
        # Take the first user message per correlation_id
        user_msgs: dict[uuid.UUID, str] = {}
        for r in msg_rows:
            if r.correlation_id not in user_msgs and r.content:
                user_msgs[r.correlation_id] = r.content

    traces = []
    for r in rows:
        errors = error_counts.get(r.correlation_id, 0)
        tools = tc_counts.get(r.correlation_id, 0)
        msg = user_msgs.get(r.correlation_id, "")
        msg_preview = (msg[:80] + "…") if len(msg) > 80 else msg
        msg_preview = msg_preview.replace("\n", " ") if msg_preview else None
        traces.append({
            "correlation_id": str(r.correlation_id),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "tool_count": tools,
            "event_count": r.event_count,
            "error_count": errors,
            "user_message_preview": msg_preview or None,
        })

    return json.dumps({"count": len(traces), "traces": traces}, ensure_ascii=False)

_TIMELINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["tool_call", "trace_event"]},
        "timestamp": {"type": ["string", "null"]},
        "tool_name": {"type": "string"},
        "tool_type": {"type": "string"},
        "iteration": {"type": ["integer", "null"]},
        "duration_ms": {"type": ["integer", "null"]},
        "status": {"type": "string"},
        "args": {"type": "object"},
        "result_preview": {"type": "string"},
        "event_type": {"type": "string"},
        "event_name": {"type": ["string", "null"]},
        "count": {"type": ["integer", "null"]},
        "data": {"type": ["object", "null"]},
    },
    "required": ["type", "timestamp"],
}

@register({
    "type": "function",
    "function": {
        "name": "get_trace",
        "description": (
            "Read trace data from conversation turns. Two top-level modes: "
            "(1) Detail (correlation_id given or omitted for current turn). "
            "Sub-modes via `mode`: `summary` (default) returns turn metadata + a phase index "
            "(phase_name → item_count); `phase` returns just the items in one phase, paginated "
            "via `cursor`/`limit`; `full` returns the entire merged timeline (legacy). "
            "Use summary first to see what's there, then drill into a named phase. "
            "(2) List (event_type given): scan recent TraceEvent rows of that type across "
            "all turns, returned as a JSON array of {correlation_id, bot_id, created_at, data}. "
            "Use list_session_traces to find correlation_ids with errors."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "correlation_id": {
                    "type": "string",
                    "description": (
                        "UUID of the turn to inspect. Can also be passed as trace_id or id. Omit to inspect the current turn."
                    ),
                },
                "trace_id": {
                    "type": "string",
                    "description": "Alias for correlation_id.",
                },
                "id": {
                    "type": "string",
                    "description": "Alias for correlation_id.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["summary", "phase", "full"],
                    "description": (
                        "Detail-mode behavior. `summary` (default): metadata + phase index, "
                        "no inner data — cheap to read. `phase`: items in one named phase, "
                        "paginated by cursor/limit. `full`: entire merged timeline (legacy)."
                    ),
                },
                "phase": {
                    "type": "string",
                    "description": (
                        "Detail mode + mode=phase: name of the phase to read (matches a "
                        "phase from the summary's phase index). Phase names are either "
                        "`tool_calls` (the bucket of all LLM tool invocations on this turn) "
                        "or a TraceEvent.event_type (e.g. `discovery_summary`, `skill_index`, "
                        "`tool_retrieval`, `token_usage`, `error`)."
                    ),
                },
                "cursor": {
                    "type": "integer",
                    "description": (
                        "Detail mode + mode=phase: zero-based offset into the phase's items "
                        "(default 0). Paginate by passing the previous response's `next_cursor`."
                    ),
                },
                "event_type": {
                    "type": "string",
                    "description": (
                        "List mode: filter TraceEvent rows by event_type (e.g. 'discovery_summary', "
                        "'skill_index'). Returns a JSON array of recent matching events."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "List mode: maximum number of events to return (default 50, max 500). "
                        "Detail mode + mode=phase: page size (default 50, max 200)."
                    ),
                },
                "bot_id": {
                    "type": "string",
                    "description": (
                        "List mode: optional filter restricting returned events to one bot."
                    ),
                },
                "include_user_message": {
                    "type": "boolean",
                    "description": (
                        "List mode: when true, each returned event also includes the "
                        "first user message for its correlation_id (truncated to ~400 "
                        "chars). Useful for auditing why a ranker/discovery event "
                        "fired the way it did — the message reveals user intent that "
                        "the trace payload alone doesn't capture."
                    ),
                },
            },
            "required": [],
        },
    },
}, returns={
    "oneOf": [
        {
            "description": "List mode (event_type given) — array of matching trace events",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "correlation_id": {"type": ["string", "null"]},
                    "bot_id": {"type": ["string", "null"]},
                    "event_type": {"type": "string"},
                    "created_at": {"type": ["string", "null"]},
                    "data": {},
                    "user_message": {"type": ["string", "null"]},
                },
                "required": ["event_type"],
            },
        },
        {
            "description": "Detail mode + mode=summary — turn metadata + phase index",
            "type": "object",
            "properties": {
                "correlation_id": {"type": "string"},
                "started_at": {"type": ["string", "null"]},
                "ended_at": {"type": ["string", "null"]},
                "tool_call_count": {"type": "integer"},
                "event_count": {"type": "integer"},
                "error_count": {"type": "integer"},
                "phases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "kind": {"type": "string", "enum": ["tool_call", "trace_event"]},
                            "item_count": {"type": "integer"},
                            "first_at": {"type": ["string", "null"]},
                            "last_at": {"type": ["string", "null"]},
                        },
                        "required": ["name", "kind", "item_count"],
                    },
                },
            },
            "required": ["correlation_id", "phases"],
        },
        {
            "description": "Detail mode + mode=phase — paginated items in one phase",
            "type": "object",
            "properties": {
                "correlation_id": {"type": "string"},
                "phase": {"type": "string"},
                "total_in_phase": {"type": "integer"},
                "cursor": {"type": "integer"},
                "next_cursor": {"type": ["integer", "null"]},
                "items": {"type": "array", "items": _TIMELINE_ITEM_SCHEMA},
            },
            "required": ["correlation_id", "phase", "items"],
        },
        {
            "description": "Detail mode + mode=full — full timeline for one turn",
            "type": "object",
            "properties": {
                "correlation_id": {"type": "string"},
                "tool_call_count": {"type": "integer"},
                "event_count": {"type": "integer"},
                "timeline": {"type": "array", "items": _TIMELINE_ITEM_SCHEMA},
            },
            "required": ["correlation_id", "timeline"],
        },
        {
            "description": "Error response",
            "type": "object",
            "properties": {"error": {"type": "string"}},
            "required": ["error"],
        },
    ],
})
async def get_trace(
    correlation_id: str | None = None,
    trace_id: str | None = None,
    id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
    bot_id: str | None = None,
    include_user_message: bool = False,
    mode: str = "summary",
    phase: str | None = None,
    cursor: int = 0,
) -> str:
    # ------------------------------------------------------------------
    # List mode — event_type given: return recent events of that type as
    # a JSON array. Separate code path; no correlation resolution.
    # ------------------------------------------------------------------
    if event_type:
        capped_limit = max(1, min(int(limit or 50), 500))
        async with async_session() as db:
            q = (
                select(TraceEvent)
                .where(TraceEvent.event_type == event_type)
                .order_by(TraceEvent.created_at.desc())
                .limit(capped_limit)
            )
            if bot_id:
                q = q.where(TraceEvent.bot_id == bot_id)
            rows = (await db.execute(q)).scalars().all()

            user_messages: dict[uuid.UUID, str] = {}
            if include_user_message and rows:
                # Fetch first user message per correlation_id in one batch
                corr_ids = [r.correlation_id for r in rows if r.correlation_id]
                if corr_ids:
                    msg_rows = (await db.execute(
                        select(Message.correlation_id, Message.content)
                        .where(
                            Message.correlation_id.in_(corr_ids),
                            Message.role == "user",
                        )
                        .order_by(Message.created_at)
                    )).all()
                    for mr in msg_rows:
                        if mr.correlation_id in user_messages:
                            continue  # keep the first user message per turn
                        if not mr.content:
                            continue
                        content = mr.content
                        if len(content) > _USER_MESSAGE_PREVIEW_CHARS:
                            content = content[:_USER_MESSAGE_PREVIEW_CHARS] + "…"
                        user_messages[mr.correlation_id] = content.replace("\n", " ")

        out: list[dict] = []
        for r in rows:
            entry: dict = {
                "correlation_id": str(r.correlation_id) if r.correlation_id else None,
                "bot_id": r.bot_id,
                "event_type": r.event_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "data": r.data,
            }
            if include_user_message:
                entry["user_message"] = (
                    user_messages.get(r.correlation_id) if r.correlation_id else None
                )
            out.append(entry)
        return json.dumps(out, ensure_ascii=False, default=str)

    # Fuzzy pick the first defined parameter in the order correlation_id, trace_id, id
    param_val = correlation_id or trace_id or id
    if param_val:
        try:
            corr_id = uuid.UUID(param_val)
        except ValueError:
            return json.dumps({"error": f"Invalid correlation_id/trace_id/id: {param_val!r}"}, ensure_ascii=False)
    else:
        corr_id = current_correlation_id.get()
        if not corr_id:
            return json.dumps({"error": "No correlation ID in context — trace not available for this turn."}, ensure_ascii=False)

    async with async_session() as db:
        tool_calls = (await db.execute(
            select(ToolCall)
            .where(ToolCall.correlation_id == corr_id)
            .order_by(ToolCall.created_at)
        )).scalars().all()

        trace_events = (await db.execute(
            select(TraceEvent)
            .where(TraceEvent.correlation_id == corr_id)
            .order_by(TraceEvent.created_at)
        )).scalars().all()

    if not tool_calls and not trace_events:
        return json.dumps({"error": f"No trace data found for correlation_id={corr_id}."}, ensure_ascii=False)

    # Merge by created_at — same ordering all three sub-modes share.
    merged: list[tuple[str, object, object]] = []
    for tc in tool_calls:
        merged.append(("tool_call", tc.created_at, tc))
    for te in trace_events:
        merged.append(("trace_event", te.created_at, te))
    merged.sort(key=lambda x: x[1] or "")

    timeline: list[dict] = []
    for kind, ts, obj in merged:
        ts_str = ts.isoformat() if ts else None
        if kind == "tool_call":
            tc = obj
            args = tc.arguments or {}
            args_str = json.dumps(args, ensure_ascii=False)
            result_preview = (tc.result or "")[:500]
            if len(tc.result or "") > 500:
                result_preview += "…"
            timeline.append({
                "type": "tool_call",
                "timestamp": ts_str,
                "tool_name": tc.tool_name,
                "tool_type": tc.tool_type,
                "iteration": tc.iteration,
                "duration_ms": tc.duration_ms,
                "status": f"ERROR: {tc.error}" if tc.error else "ok",
                "args": args if len(args_str) <= 2000 else {"_truncated": args_str[:2000] + "…"},
                "result_preview": result_preview,
            })
        else:
            te = obj
            data = te.data
            data_str = json.dumps(data, ensure_ascii=False) if data else ""
            timeline.append({
                "type": "trace_event",
                "timestamp": ts_str,
                "event_type": te.event_type,
                "event_name": te.event_name,
                "count": te.count,
                "duration_ms": te.duration_ms,
                "data": data if not data_str or len(data_str) <= 2000 else {"_truncated": data_str[:2000] + "…"},
            })

    requested_mode = (mode or "summary").lower()
    if requested_mode not in ("summary", "phase", "full"):
        return json.dumps(
            {"error": f"Invalid mode {mode!r}; expected summary | phase | full."},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # Full mode — legacy behavior, kept for callers that need the whole
    # timeline at once.
    # ------------------------------------------------------------------
    if requested_mode == "full":
        return json.dumps({
            "correlation_id": str(corr_id),
            "tool_call_count": len(tool_calls),
            "event_count": len(trace_events),
            "timeline": timeline,
        }, ensure_ascii=False, default=str)

    # Phase grouping rule: every tool_call falls in the "tool_calls" bucket;
    # every trace_event is bucketed by its event_type. This keeps the phase
    # list short and useful (~5–8 named phases per turn) without exposing
    # implementation detail like LLM iteration index.
    def _phase_for(item: dict) -> str:
        if item["type"] == "tool_call":
            return "tool_calls"
        return item.get("event_type") or "unknown"

    # ------------------------------------------------------------------
    # Summary mode — turn metadata + phase index, no inner data.
    # ------------------------------------------------------------------
    if requested_mode == "summary":
        # Preserve insertion order of first appearance so the index reads
        # in chronological phase order.
        phase_index: dict[str, dict] = {}
        for item in timeline:
            name = _phase_for(item)
            entry = phase_index.get(name)
            ts_str = item.get("timestamp")
            if entry is None:
                phase_index[name] = {
                    "name": name,
                    "kind": item["type"],
                    "item_count": 1,
                    "first_at": ts_str,
                    "last_at": ts_str,
                }
            else:
                entry["item_count"] += 1
                if ts_str:
                    entry["last_at"] = ts_str

        error_count = sum(
            1 for it in timeline
            if it["type"] == "tool_call" and isinstance(it.get("status"), str) and it["status"].startswith("ERROR")
        ) + sum(
            1 for it in timeline
            if it["type"] == "trace_event" and it.get("event_type") == "error"
        )

        started_at = timeline[0]["timestamp"] if timeline else None
        ended_at = timeline[-1]["timestamp"] if timeline else None

        return json.dumps({
            "correlation_id": str(corr_id),
            "started_at": started_at,
            "ended_at": ended_at,
            "tool_call_count": len(tool_calls),
            "event_count": len(trace_events),
            "error_count": error_count,
            "phases": list(phase_index.values()),
        }, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # Phase mode — one phase, paginated.
    # ------------------------------------------------------------------
    if not phase:
        return json.dumps(
            {"error": "phase=<name> is required when mode=phase. Call mode=summary first to discover phase names."},
            ensure_ascii=False,
        )

    phase_items = [it for it in timeline if _phase_for(it) == phase]
    if not phase_items:
        return json.dumps(
            {"error": f"Phase {phase!r} not present in correlation_id={corr_id}. Call mode=summary to see available phases."},
            ensure_ascii=False,
        )

    page_limit = max(1, min(int(limit) if limit is not None else 50, 200))
    start = max(0, int(cursor or 0))
    end = start + page_limit
    sliced = phase_items[start:end]
    next_cursor: int | None = end if end < len(phase_items) else None

    return json.dumps({
        "correlation_id": str(corr_id),
        "phase": phase,
        "total_in_phase": len(phase_items),
        "cursor": start,
        "next_cursor": next_cursor,
        "items": sliced,
    }, ensure_ascii=False, default=str)
