"""Agent self-debugging tool: read the current request's trace events and tool calls."""
import json

from sqlalchemy import select

from app.agent.context import current_correlation_id
from app.db.engine import async_session
from app.db.models import ToolCall, TraceEvent
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "get_trace",
        "description": (
            "Read the full trace of the current conversation turn: all RAG retrieval events, "
            "tool calls (with arguments and results), token usage, and errors. "
            "Use this when you suspect a RAG failure, incorrect tool result, or missing context — "
            "it lets you reason about what actually happened."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})
async def get_trace() -> str:
    correlation_id = current_correlation_id.get()
    if not correlation_id:
        return "No correlation ID in context — trace not available for this turn."

    async with async_session() as db:
        tool_calls = (
            await db.execute(
                select(ToolCall)
                .where(ToolCall.correlation_id == correlation_id)
                .order_by(ToolCall.created_at)
            )
        ).scalars().all()

        trace_events = (
            await db.execute(
                select(TraceEvent)
                .where(TraceEvent.correlation_id == correlation_id)
                .order_by(TraceEvent.created_at)
            )
        ).scalars().all()

    # Merge by created_at
    merged = []
    for tc in tool_calls:
        merged.append(("tool_call", tc.created_at, tc))
    for te in trace_events:
        merged.append(("trace_event", te.created_at, te))
    merged.sort(key=lambda x: x[1])

    if not merged:
        return f"No trace events found for correlation_id={correlation_id}."

    lines = [f"Trace for correlation_id={correlation_id}\n"]
    for kind, ts, obj in merged:
        ts_str = ts.strftime("%H:%M:%S.%f")[:-3] if ts else "?"
        if kind == "tool_call":
            tc = obj
            args_str = json.dumps(tc.arguments or {})
            if len(args_str) > 500:
                args_str = args_str[:500] + "..."
            result_str = (tc.result or "")[:500]
            if len(tc.result or "") > 500:
                result_str += "..."
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
                    data_str = data_str[:500] + "..."
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
