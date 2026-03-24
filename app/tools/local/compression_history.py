"""Drill-down tool for context compression — lets the agent fetch specific messages."""
import json
import logging

from app.agent.context import current_compression_history
from app.services.compression import _stringify_content, _stringify_tool_calls
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_message_detail",
        "description": (
            "Retrieve full message content from the compressed conversation history. "
            "Use this when the conversation summary references [msg:N] and you need "
            "the complete details. You can request a range of messages or search by keyword."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_index": {
                    "type": "integer",
                    "description": "Starting message index from [msg:N] reference.",
                },
                "end_index": {
                    "type": "integer",
                    "description": "End message index (inclusive). Max 20 messages per request. Defaults to start_index.",
                },
                "query": {
                    "type": "string",
                    "description": "Keyword search across all compressed messages. Returns matching messages with their indices.",
                },
            },
        },
    },
})
async def get_message_detail(
    start_index: int | None = None,
    end_index: int | None = None,
    query: str | None = None,
) -> str:
    history = current_compression_history.get()
    if history is None:
        return json.dumps({"error": "No compressed history available. Context compression is not active for this turn."})

    if query:
        q_lower = query.lower()
        matches: list[str] = []
        for idx, msg in enumerate(history):
            content = _stringify_content(msg.get("content", ""))
            tc_text = ""
            if msg.get("tool_calls"):
                tc_text = _stringify_tool_calls(msg["tool_calls"])
            full_text = f"{content} {tc_text}"
            if q_lower in full_text.lower():
                matches.append(_format_detail(idx, msg))
                if len(matches) >= 20:
                    break
        if not matches:
            return json.dumps({"result": f"No messages matching '{query}' found.", "total_messages": len(history)})
        return "\n\n".join(matches)

    if start_index is None:
        return json.dumps({"error": "Provide start_index or query.", "total_messages": len(history)})

    if end_index is None:
        end_index = start_index

    # Clamp indices
    start_index = max(0, start_index)
    end_index = min(len(history) - 1, end_index)
    if end_index - start_index >= 20:
        end_index = start_index + 19

    lines: list[str] = []
    for idx in range(start_index, end_index + 1):
        if 0 <= idx < len(history):
            lines.append(_format_detail(idx, history[idx]))

    if not lines:
        return json.dumps({"error": f"Index out of range. Valid range: 0-{len(history) - 1}"})

    return "\n\n".join(lines)


def _format_detail(idx: int, msg: dict) -> str:
    """Format a message with full content for drill-down."""
    role = msg.get("role", "?")
    content = _stringify_content(msg.get("content", ""))

    parts = [f"[msg:{idx}] {role}:"]
    if content:
        parts.append(content)
    if msg.get("tool_calls"):
        for tc in msg["tool_calls"]:
            fn = tc.get("function", {})
            name = fn.get("name", "?")
            args = fn.get("arguments", "")
            parts.append(f"  → tool_call: {name}({args})")
    if role == "tool" and msg.get("tool_call_id"):
        parts[0] = f"[msg:{idx}] tool(call_id={msg['tool_call_id']}):"

    return "\n".join(parts)
