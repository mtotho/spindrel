"""Tool call routing, execution, recording, and result processing."""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agent.llm import _summarize_tool_result
from app.agent.recording import _record_tool_call, _record_trace_event
from app.agent.tracing import _trace
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending
from app.config import settings
from app.tools.client_tools import is_client_tool
from app.tools.mcp import call_mcp_tool, get_mcp_server_for_tool, is_mcp_tool
from app.tools.local.memory import call_memory_tool
from app.tools.registry import call_local_tool, is_local_tool
from app.tools.local.persona import call_persona_tool
from app.tools.local.knowledge import call_knowledge_tool

logger = logging.getLogger(__name__)


@dataclass
class ToolCallResult:
    """Result of dispatching a single tool call."""
    result: str = ""
    result_for_llm: str = ""
    was_summarized: bool = False
    embedded_client_action: dict | None = None
    tool_event: dict[str, Any] = field(default_factory=dict)
    pre_events: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0


async def dispatch_tool_call(
    *,
    name: str,
    args: str,
    tool_call_id: str,
    bot_id: str,
    bot_memory: Any,
    session_id: uuid.UUID | None,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    iteration: int,
    provider_id: str | None,
    # Summarization config
    summarize_enabled: bool,
    summarize_threshold: int,
    summarize_model: str,
    summarize_max_tokens: int,
    summarize_exclude: set[str],
    # Compaction flag for event tagging
    compaction: bool,
) -> ToolCallResult:
    """Route a single tool call to the appropriate handler, record it, and build the result event."""
    from app.agent.message_utils import _event_with_compaction_tag

    result_obj = ToolCallResult()
    t0 = time.monotonic()
    _tc_type = "local"
    _tc_server: str | None = None

    if is_client_tool(name):
        _tc_type = "client"
        request_id = str(uuid.uuid4())
        try:
            tool_args = json.loads(args) if args else {}
        except (json.JSONDecodeError, TypeError):
            tool_args = {}
        result_obj.pre_events.append(_event_with_compaction_tag({
            "type": "tool_request",
            "request_id": request_id,
            "tool": name,
            "arguments": tool_args,
        }, compaction))
        future = create_pending(request_id)
        try:
            result = await asyncio.wait_for(future, timeout=CLIENT_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Client tool %s timed out (request %s)", name, request_id)
            result = json.dumps({"error": "Client did not respond in time"})
    elif is_local_tool(name):
        _tc_type = "local"
        if name in (
            "search_memories",
            "save_memory",
            "purge_memory",
            "merge_memories",
            "promote_memories_to_knowledge",
        ) and session_id and client_id:
            # Get user_id for user-scoped cross-bot memory
            try:
                from app.agent.bots import get_bot as _get_bot
                _user_id = _get_bot(bot_id).user_id
            except Exception:
                _user_id = None
            result = await call_memory_tool(
                name,
                args or "{}",
                session_id,
                client_id,
                bot_id,
                bot_memory,
                correlation_id=correlation_id,
                channel_id=channel_id,
                user_id=_user_id,
            )
        elif name in ("update_persona", "append_to_persona", "edit_persona"):
            result = await call_persona_tool(name, args or "{}", bot_id)
        elif name in (
            "upsert_knowledge",
            "get_knowledge",
            "search_knowledge",
            "list_knowledge_bases",
            "append_to_knowledge",
            "edit_knowledge",
            "delete_knowledge",
            "pin_knowledge",
            "unpin_knowledge",
            "set_knowledge_similarity_threshold",
        ) and client_id:
            result = await call_knowledge_tool(
                name,
                args or "{}",
                bot_id,
                client_id,
                session_id=session_id,
                channel_id=channel_id,
                fallback_threshold=settings.KNOWLEDGE_SIMILARITY_THRESHOLD,
            )
        else:
            result = await call_local_tool(name, args)
    elif is_mcp_tool(name):
        _tc_type = "mcp"
        _tc_server = get_mcp_server_for_tool(name)
        result = await call_mcp_tool(name, args)
    else:
        result = json.dumps({"error": f"Unknown tool: {name}"})

    _tc_duration = int((time.monotonic() - t0) * 1000)
    result_obj.duration_ms = _tc_duration

    # Record tool call
    _tc_error: str | None = None
    try:
        _parsed_r = json.loads(result)
        if isinstance(_parsed_r, dict) and "error" in _parsed_r:
            _tc_error = str(_parsed_r["error"])
    except Exception:
        pass
    try:
        _tc_args = json.loads(args or "{}")
        if not isinstance(_tc_args, dict):
            _tc_args = {}
    except Exception:
        _tc_args = {}
    asyncio.create_task(_record_tool_call(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        tool_name=name,
        tool_type=_tc_type,
        server_name=_tc_server,
        iteration=iteration,
        arguments=_tc_args,
        result=result,
        error=_tc_error,
        duration_ms=_tc_duration,
        correlation_id=correlation_id,
    ))

    result_obj.result = result

    # Extract embedded client_action
    result_for_llm = result
    try:
        parsed_tool = json.loads(result_for_llm)
        if isinstance(parsed_tool, dict) and "client_action" in parsed_tool:
            result_obj.embedded_client_action = parsed_tool["client_action"]
            result_for_llm = parsed_tool.get("message", "Done.")
    except (json.JSONDecodeError, TypeError):
        pass

    # Summarize if needed
    _orig_len = len(result_for_llm)
    _was_summarized = False
    if (
        summarize_enabled
        and name not in summarize_exclude
        and (_tc_server is None or _tc_server not in summarize_exclude)
        and len(result_for_llm) > summarize_threshold
    ):
        _was_summarized = True
        result_for_llm = await _summarize_tool_result(
            tool_name=name,
            content=result_for_llm,
            model=summarize_model,
            max_tokens=summarize_max_tokens,
            provider_id=provider_id,
        )
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot_id,
                client_id=client_id,
                event_type="tool_result_summarization",
                data={
                    "tool_name": name,
                    "original_length": _orig_len,
                    "summarized_length": len(result_for_llm),
                },
            ))

    result_obj.result_for_llm = result_for_llm
    result_obj.was_summarized = _was_summarized

    result_preview = result_for_llm[:200] + "..." if len(result_for_llm) > 200 else result_for_llm
    logger.debug("Tool result [%s]: %s", name, result_preview)

    # Build tool_event
    tool_event: dict[str, Any] = {"type": "tool_result", "tool": name}
    if _was_summarized:
        tool_event["summarized"] = True
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and "error" in parsed:
            err = parsed["error"]
            logger.warning("Tool %s returned error: %s", name, err)
            tool_event["error"] = err
            _trace("← %s error: %s", name, str(err)[:80])
        else:
            _trace("← %s (%d chars)", name, len(result_for_llm))
    except (json.JSONDecodeError, TypeError):
        _trace("← %s (%d chars)", name, len(result_for_llm))
    if name == "search_memories":
        if result == "No relevant memories found." or result == "No search query provided.":
            tool_event["memory_count"] = 0
        elif result.startswith("Relevant memories:\n\n"):
            body = result[len("Relevant memories:\n\n"):]
            tool_event["memory_count"] = 1 + body.count("\n\n---\n\n")
            if tool_event["memory_count"] > 0:
                first = body.split("\n\n---\n\n")[0].strip()
                tool_event["memory_preview"] = (first[:120] + "…") if len(first) > 120 else first
    elif name == "save_memory" and result == "Memory saved.":
        tool_event["saved"] = True
    result_obj.tool_event = tool_event

    return result_obj
