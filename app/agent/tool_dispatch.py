"""Tool call routing, execution, recording, and result processing."""

import asyncio
import json
import logging
import time
import uuid

from app.utils import safe_create_task
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
    injected_images: list[dict] | None = None  # [{"mime_type": str, "base64": str}]
    tool_event: dict[str, Any] = field(default_factory=dict)
    pre_events: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    # Approval fields (Phase 3)
    needs_approval: bool = False
    approval_id: str | None = None
    approval_timeout: int = 300
    approval_reason: str | None = None


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
    # Policy override — skip check when re-dispatching after approval
    skip_policy: bool = False,
    # Authorization — if set, only these tool names are allowed
    allowed_tool_names: set[str] | None = None,
) -> ToolCallResult:
    """Route a single tool call to the appropriate handler, record it, and build the result event."""
    from app.agent.message_utils import _event_with_compaction_tag

    result_obj = ToolCallResult()

    # --- Authorization check ---
    if allowed_tool_names is not None and name not in allowed_tool_names:
        _trace("✗ %s not authorized for bot %s", name, bot_id)
        _auth_err = f"Tool '{name}' is not available. It must be explicitly assigned to this bot."
        result_obj.result = json.dumps({"error": _auth_err})
        result_obj.result_for_llm = result_obj.result
        result_obj.tool_event = {"type": "tool_result", "tool": name, "error": _auth_err}
        return result_obj

    # --- Policy check ---
    if not skip_policy:
        try:
            _tc_args_for_policy: dict = {}
            try:
                _tc_args_for_policy = json.loads(args or "{}") if args else {}
                if not isinstance(_tc_args_for_policy, dict):
                    _tc_args_for_policy = {}
            except Exception:
                pass
            decision = await _check_tool_policy(
                bot_id, name, _tc_args_for_policy,
                correlation_id=str(correlation_id) if correlation_id else None,
            )
            if decision is not None:
                if decision.action == "deny":
                    result_obj.result = json.dumps({"error": f"Tool call denied by policy: {decision.reason or 'no reason'}"})
                    result_obj.result_for_llm = result_obj.result
                    result_obj.tool_event = {"type": "tool_result", "tool": name, "error": f"Denied by policy: {decision.reason or 'no reason'}"}
                    _trace("✗ %s denied by policy (rule %s)", name, decision.rule_id)
                    return result_obj
                elif decision.action == "require_approval":
                    # Determine tool type for the approval record
                    if is_client_tool(name):
                        _ap_type = "client"
                    elif is_mcp_tool(name):
                        _ap_type = "mcp"
                    else:
                        _ap_type = "local"
                    approval_id = await _create_approval_record(
                        session_id=session_id,
                        channel_id=channel_id,
                        bot_id=bot_id,
                        client_id=client_id,
                        correlation_id=correlation_id,
                        tool_name=name,
                        tool_type=_ap_type,
                        arguments=_tc_args_for_policy,
                        policy_rule_id=decision.rule_id,
                        reason=decision.reason,
                        timeout=decision.timeout,
                    )
                    result_obj.needs_approval = True
                    result_obj.approval_id = approval_id
                    result_obj.approval_timeout = decision.timeout
                    result_obj.approval_reason = decision.reason
                    result_obj.result_for_llm = json.dumps({"status": "pending_approval", "reason": decision.reason})
                    result_obj.tool_event = {"type": "tool_result", "tool": name, "pending_approval": True}
                    _trace("⏳ %s requires approval (rule %s)", name, decision.rule_id)
                    return result_obj
        except Exception:
            logger.exception("Policy check failed for %s — denying by default", name)
            _policy_err = "Tool call denied: policy evaluation error. Please retry."
            result_obj.result = json.dumps({"error": _policy_err})
            result_obj.result_for_llm = result_obj.result
            result_obj.tool_event = {"type": "tool_result", "tool": name, "error": _policy_err}
            return result_obj

    # Determine tool type for hook data
    if is_client_tool(name):
        _pre_hook_type = "client"
    elif is_mcp_tool(name):
        _pre_hook_type = "mcp"
    else:
        _pre_hook_type = "local"

    # Fire before_tool_execution lifecycle hook (after auth/policy checks pass)
    from app.agent.hooks import fire_hook, HookContext
    safe_create_task(fire_hook("before_tool_execution", HookContext(
        bot_id=bot_id, session_id=session_id, channel_id=channel_id,
        client_id=client_id, correlation_id=correlation_id,
        extra={
            "tool_name": name,
            "tool_type": _pre_hook_type,
            "args": args,
            "iteration": iteration + 1,
        },
    )))

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

    # Redact known secrets from the raw result before storage
    from app.services.secret_registry import redact as _redact_secrets
    result_obj.result = _redact_secrets(result)

    # Extract embedded client_action or injected_images
    result_for_llm = result
    try:
        parsed_tool = json.loads(result_for_llm)
        if isinstance(parsed_tool, dict):
            if "client_action" in parsed_tool:
                result_obj.embedded_client_action = parsed_tool["client_action"]
                result_for_llm = parsed_tool.get("message", "Done.")
            elif "injected_images" in parsed_tool:
                result_obj.injected_images = parsed_tool["injected_images"]
                result_for_llm = parsed_tool.get("message", "Image loaded for analysis.")
    except (json.JSONDecodeError, TypeError):
        pass

    # Redact known secrets before summarization or LLM consumption
    result_for_llm = _redact_secrets(result_for_llm)

    # Summarize if needed
    _orig_len = len(result_for_llm)
    _was_summarized = False
    _will_summarize = (
        summarize_enabled
        and name not in summarize_exclude
        and (_tc_server is None or _tc_server not in summarize_exclude)
        and len(result_for_llm) > summarize_threshold
    )

    # Pre-generate tool call ID so we can reference it in the retrieval hint
    _tc_record_id = uuid.uuid4() if _will_summarize else None

    # Record tool call (store full result when summarization will occur)
    safe_create_task(_record_tool_call(
        id=_tc_record_id,
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        tool_name=name,
        tool_type=_tc_type,
        server_name=_tc_server,
        iteration=iteration,
        arguments=_tc_args,
        result=result_obj.result,  # use redacted result
        error=_tc_error,
        duration_ms=_tc_duration,
        correlation_id=correlation_id,
        store_full_result=_will_summarize,
    ))

    if _will_summarize:
        _was_summarized = True
        result_for_llm = await _summarize_tool_result(
            tool_name=name,
            content=result_for_llm,
            model=summarize_model,
            max_tokens=summarize_max_tokens,
            provider_id=provider_id,
        )
        # Append retrieval hint so the bot can fetch full output
        result_for_llm += (
            f"\n\n[Full output stored — use read_conversation_history"
            f"(section='tool:{_tc_record_id}') to retrieve]"
        )
        if correlation_id is not None:
            safe_create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot_id,
                client_id=client_id,
                event_type="tool_result_summarization",
                data={
                    "tool_name": name,
                    "original_length": _orig_len,
                    "summarized_length": len(result_for_llm),
                    "tool_call_record_id": str(_tc_record_id),
                },
            ))

    result_obj.result_for_llm = result_for_llm
    result_obj.was_summarized = _was_summarized

    result_preview = result_for_llm[:200] + "..." if len(result_for_llm) > 200 else result_for_llm
    logger.debug("Tool result [%s]: %s", name, result_preview)

    # Build tool_event — use redacted result to avoid leaking secrets
    # in SSE events, log output, or memory previews
    _redacted_result = result_obj.result
    tool_event: dict[str, Any] = {"type": "tool_result", "tool": name}
    if _was_summarized:
        tool_event["summarized"] = True
    try:
        parsed = json.loads(_redacted_result)
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
        if _redacted_result == "No relevant memories found." or _redacted_result == "No search query provided.":
            tool_event["memory_count"] = 0
        elif _redacted_result.startswith("Relevant memories:\n\n"):
            body = _redacted_result[len("Relevant memories:\n\n"):]
            tool_event["memory_count"] = 1 + body.count("\n\n---\n\n")
            if tool_event["memory_count"] > 0:
                first = body.split("\n\n---\n\n")[0].strip()
                tool_event["memory_preview"] = (first[:120] + "…") if len(first) > 120 else first
    elif name == "save_memory" and _redacted_result == "Memory saved.":
        tool_event["saved"] = True
    result_obj.tool_event = tool_event

    return result_obj


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------

async def _check_tool_policy(
    bot_id: str, tool_name: str, arguments: dict,
    *, correlation_id: str | None = None,
) -> Any:
    """Evaluate tool policy. Returns PolicyDecision or None (allow = skip overhead)."""
    from app.config import settings
    from app.db.engine import async_session
    from app.services.tool_policies import evaluate_tool_policy

    if not settings.TOOL_POLICY_ENABLED:
        return None

    # Session-scoped allow: if this tool was approved earlier in this conversation,
    # skip the full policy evaluation.  This is the key UX improvement — after one
    # approval, the user isn't asked again for the same tool in the same run.
    from app.agent.session_allows import is_session_allowed
    if is_session_allowed(correlation_id, tool_name):
        return None

    async with async_session() as db:
        decision = await evaluate_tool_policy(db, bot_id, tool_name, arguments)
    if decision.action == "allow":
        return None
    return decision


async def _create_approval_record(
    *,
    session_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    bot_id: str,
    client_id: str | None,
    correlation_id: uuid.UUID | None,
    tool_name: str,
    tool_type: str,
    arguments: dict,
    policy_rule_id: str | None,
    reason: str | None,
    timeout: int,
) -> str:
    """Create a ToolApproval DB record and return its ID as string."""
    from app.db.engine import async_session
    from app.db.models import ToolApproval

    # Resolve dispatch info from context vars for notification routing
    from app.agent.context import current_dispatch_type, current_dispatch_config
    dispatch_type = current_dispatch_type.get(None)
    dispatch_config = current_dispatch_config.get(None)

    approval = ToolApproval(
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        client_id=client_id,
        correlation_id=correlation_id,
        tool_name=tool_name,
        tool_type=tool_type,
        arguments=arguments,
        policy_rule_id=uuid.UUID(policy_rule_id) if policy_rule_id else None,
        reason=reason,
        status="pending",
        dispatch_type=dispatch_type,
        dispatch_metadata=dispatch_config,
        timeout_seconds=timeout,
    )
    async with async_session() as db:
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        approval_id = str(approval.id)

    # Fire-and-forget notification via dispatcher
    if dispatch_type and dispatch_config:
        safe_create_task(_notify_approval_request(
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            approval_id=approval_id,
            bot_id=bot_id,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
        ))

    return approval_id


async def _notify_approval_request(
    *,
    dispatch_type: str,
    dispatch_config: dict,
    approval_id: str,
    bot_id: str,
    tool_name: str,
    arguments: dict,
    reason: str | None,
) -> None:
    """Send approval notification via the appropriate dispatcher."""
    try:
        from app.agent import dispatchers
        dispatcher = dispatchers.get(dispatch_type)
        if hasattr(dispatcher, "request_approval"):
            await dispatcher.request_approval(
                dispatch_config=dispatch_config,
                approval_id=approval_id,
                bot_id=bot_id,
                tool_name=tool_name,
                arguments=arguments,
                reason=reason,
            )
        else:
            # Fallback: post a text message
            args_preview = json.dumps(arguments, indent=2)[:300]
            text = (
                f"🔒 *Tool approval required*\n"
                f"Bot: `{bot_id}` | Tool: `{tool_name}`\n"
                f"Reason: {reason or 'Policy requires approval'}\n"
                f"```\n{args_preview}\n```\n"
                f"Approval ID: `{approval_id}`\n"
                f"Use `POST /api/v1/approvals/{approval_id}/decide` to approve or deny."
            )
            await dispatcher.post_message(dispatch_config, text, bot_id=bot_id)
    except Exception:
        logger.exception("Failed to send approval notification for %s", approval_id)
