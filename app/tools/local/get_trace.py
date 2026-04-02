"""Agent self-debugging tools: browse conversation traces and inspect specific turns."""
import json
import uuid

from sqlalchemy import func, select

from app.agent.context import current_correlation_id, current_session_id
from app.db.engine import async_session
from app.db.models import Message, ToolCall, TraceEvent
from app.tools.registry import register


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
})
async def list_session_traces(limit: int = 10) -> str:
    session_id = current_session_id.get()
    if not session_id:
        return "No conversation context available."

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
            return f"No trace events found for this conversation."

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

    lines = [f"Recent traces (newest first):\n"]
    for r in rows:
        ts = r.started_at.strftime("%m-%d %H:%M") if r.started_at else "?"
        errors = error_counts.get(r.correlation_id, 0)
        tools = tc_counts.get(r.correlation_id, 0)
        msg = user_msgs.get(r.correlation_id, "")
        msg_preview = (msg[:80] + "…") if len(msg) > 80 else msg
        # Strip newlines for compact display
        msg_preview = msg_preview.replace("\n", " ")

        error_flag = " ⚠ ERROR" if errors else ""
        lines.append(
            f"[{ts}] {r.correlation_id}{error_flag}\n"
            f"  tools={tools} events={r.event_count}"
            + (f" errors={errors}" if errors else "")
            + (f"\n  user: {msg_preview}" if msg_preview else "")
        )

    return "\n".join(lines)

@register({
    "type": "function",
    "function": {
        "name": "get_trace",
        "description": (
            "Read the full trace of a conversation turn: all RAG retrieval events, "
            "tool calls (with arguments and results), token usage, and errors. "
            "Defaults to the current turn. Pass a correlation_id, trace_id, or id to inspect a previous turn. "
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
                    "description": (
                        "Alias for correlation_id."
                    ),
                },
                "id": {
                    "type": "string",
                    "description": (
                        "Alias for correlation_id."
                    ),
                },
            },
            "required": [],
        },
    },
})
async def get_trace(
    correlation_id: str | None = None,
    trace_id: str | None = None,
    id: str | None = None,
) -> str:
    # Fuzzy pick the first defined parameter in the order correlation_id, trace_id, id
    param_val = correlation_id or trace_id or id
    if param_val:
        try:
            corr_id = uuid.UUID(param_val)
        except ValueError:
            return json.dumps({"error": f"Invalid correlation_id/trace_id/id: {param_val!r}"})
    else:
        corr_id = current_correlation_id.get()
        if not corr_id:
            return "No correlation ID in context — trace not available for this turn."

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
        return f"No trace data found for correlation_id={corr_id}."

    # Merge by created_at
    merged: list[tuple[str, object, object]] = []
    for tc in tool_calls:
        merged.append(("tool_call", tc.created_at, tc))
    for te in trace_events:
        merged.append(("trace_event", te.created_at, te))
    merged.sort(key=lambda x: x[1] or "")

    lines = [f"Trace for correlation_id={corr_id}\n"]
    for kind, ts, obj in merged:
        ts_str = ts.strftime("%H:%M:%S.%f")[:-3] if ts else "?"
        if kind == "tool_call":
            tc = obj
            args_str = json.dumps(tc.arguments or {})
            if len(args_str) > 500:
                args_str = args_str[:500] + "…"
            result_str = (tc.result or "")[:500]
            if len(tc.result or "") > 500:
                result_str += "…"
            status = f"ERROR: {tc.error}" if tc.error else "ok"
            lines.append(
                f"[{ts_str}] TOOL {tc.tool_name} ({tc.tool_type}) "
                f"iter={tc.iteration} dur={tc.duration_ms}ms status={status}\n"
                f"  args: {args_str}\n"
                f"  result: {result_str}"
            )
        else:
            te = obj
            data_str = ""
            if te.data:
                data_str = json.dumps(te.data)
                if len(data_str) > 500:
                    data_str = data_str[:500] + "…"
            parts = [f"[{ts_str}] EVENT {te.event_type}"]
            if te.event_name:
                parts.append(f"name={te.event_name}")
            if te.count is not None:
                parts.append(f"count={te.count}")
            if te.duration_ms is not None:
                parts.append(f"dur={te.duration_ms}ms")
            if data_str:
                parts.append(f"data={data_str}")
            lines.append(" ".join(parts))

    return "\n".join(lines)
