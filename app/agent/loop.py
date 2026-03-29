import asyncio
import json
import logging
import traceback
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context
from app.services import session_locks
from app.agent.context_assembly import AssemblyResult, assemble_context
from app.agent.message_utils import (
    _event_with_compaction_tag,
    _extract_client_actions,
    _extract_transcript,
    _merge_tool_schemas,
)
from app.agent.elevation import classify_turn, get_elevation_config
from app.agent.elevation_log import backfill_elevation_log, log_elevation
from app.agent.recording import _record_trace_event
from app.agent.llm import AccumulatedMessage, EmptyChoicesError, FallbackInfo, _llm_call, _llm_call_stream, _summarize_tool_result, last_fallback_info, strip_think_tags  # noqa: F401 — re-exported
from app.agent.tool_dispatch import dispatch_tool_call
from app.agent.tracing import _CLASSIFY_SYS_MSG, _SYS_MSG_PREFIXES, _trace  # noqa: F401 — re-exported
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas

logger = logging.getLogger(__name__)


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Ensure no message has null/missing content — some models reject it.

    Mutates *messages* in-place (replacing individual dicts where needed)
    so that callers holding a reference to the same list see the changes.
    Returning the same list keeps the API unchanged for call-sites that
    reassign: ``messages = _sanitize_messages(messages)``.
    """
    for i, m in enumerate(messages):
        if "content" not in m or m["content"] is None:
            messages[i] = {**m, "content": ""}
    return messages


@dataclass
class RunResult:
    response: str = ""
    transcript: str = ""
    client_actions: list[dict] = field(default_factory=list)


async def run_agent_tool_loop(
    messages: list[dict],
    bot: BotConfig,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    *,
    model_override: str | None = None,
    provider_id_override: str | None = None,
    turn_start: int = 0,
    native_audio: bool = False,
    user_msg_index: int | None = None,
    compaction: bool = False,
    pre_selected_tools: list[dict[str, Any]] | None = None,
    correlation_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    max_iterations: int | None = None,
    fallback_models: list[dict] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Single agent tool loop: LLM + tool calls until final response. Caller builds messages and sets context.
    When compaction=True, every yielded event gets "compaction": True.
    """
    effective_max_iterations = max_iterations or settings.AGENT_MAX_ITERATIONS
    model = model_override or bot.model
    provider_id = provider_id_override or bot.model_provider_id

    # Effective tool result summarization settings (bot-level overrides global)
    _trc = bot.tool_result_config or {}
    _eff_summarize_enabled: bool = _trc["enabled"] if "enabled" in _trc else settings.TOOL_RESULT_SUMMARIZE_ENABLED
    _eff_summarize_threshold: int = _trc.get("threshold") or settings.TOOL_RESULT_SUMMARIZE_THRESHOLD
    _eff_summarize_model: str = _trc.get("model") or settings.TOOL_RESULT_SUMMARIZE_MODEL or model
    _eff_summarize_max_tokens: int = _trc.get("max_tokens") or settings.TOOL_RESULT_SUMMARIZE_MAX_TOKENS
    _eff_summarize_exclude: set[str] = set(settings.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS) | set(_trc.get("exclude_tools") or [])

    if pre_selected_tools is not None:
        all_tools = _merge_tool_schemas(pre_selected_tools)
    else:
        # Auto-inject workspace tools when workspace is enabled
        _local_tool_names = list(bot.local_tools)
        if bot.workspace.enabled or bot.shared_workspace_id:
            from app.agent.message_utils import _WORKSPACE_TOOLS
            for wt in _WORKSPACE_TOOLS:
                if wt not in _local_tool_names:
                    _local_tool_names.append(wt)
        local_schemas = get_local_tool_schemas(_local_tool_names)
        mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
        client_schemas = get_client_tool_schemas(bot.client_tools)
        all_tools = local_schemas + mcp_schemas + client_schemas
        # Auto-inject get_skill when bot has skills configured (and tool not already included)
        if bot.skills and not any(
            t.get("function", {}).get("name") == "get_skill" for t in all_tools
        ):
            skill_schemas = get_local_tool_schemas(["get_skill"])
            all_tools = all_tools + skill_schemas
        # Merge dynamically injected tools (e.g. heartbeat_post_to_thread)
        from app.agent.context import current_injected_tools
        _injected = current_injected_tools.get()
        if _injected:
            _existing = {t["function"]["name"] for t in all_tools}
            for t in _injected:
                if t["function"]["name"] not in _existing:
                    all_tools.append(t)
    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    logger.debug("Tools available: %s", [t["function"]["name"] for t in all_tools] if all_tools else "(none)")

    transcript_emitted = False
    embedded_client_actions: list[dict] = []
    tool_calls_made: list[str] = []  # track tool names for elevation classifier

    try:
        for iteration in range(effective_max_iterations):
            # Cancellation checkpoint: before LLM call
            if session_id and session_locks.is_cancel_requested(session_id):
                logger.info("Cancellation requested for session %s (before LLM call, iteration %d)", session_id, iteration + 1)
                yield _event_with_compaction_tag({"type": "cancelled"}, compaction)
                return

            logger.debug("--- Iteration %d ---", iteration + 1)
            logger.debug("Calling LLM (%s) with %d messages", model, len(messages))

            if correlation_id is not None:
                _breakdown: dict[str, dict] = {}
                for _m in messages:
                    _role = _m.get("role", "?")
                    _content = _m.get("content") or ""
                    _chars = sum(len(str(p)) for p in _content) if isinstance(_content, list) else len(_content)
                    if _role == "assistant" and _m.get("tool_calls"):
                        _chars += sum(len(str(tc)) for tc in _m["tool_calls"])
                    _key = _role
                    if _role == "system" and isinstance(_content, str):
                        _key = _CLASSIFY_SYS_MSG(_content)
                    if _key not in _breakdown:
                        _breakdown[_key] = {"count": 0, "chars": 0}
                    _breakdown[_key]["count"] += 1
                    _breakdown[_key]["chars"] += _chars
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="context_breakdown",
                    data={
                        "breakdown": _breakdown,
                        "total_messages": len(messages),
                        "total_chars": sum(v["chars"] for v in _breakdown.values()),
                        "iteration": iteration + 1,
                    },
                ))

            # TPM rate limit check: yield wait event and sleep if needed
            from app.services.providers import check_rate_limit

            def _est_msg_chars(m: dict) -> int:
                content = m.get("content") or ""
                chars = len(content) if isinstance(content, str) else sum(
                    len(str(p)) for p in content
                ) if isinstance(content, list) else 0
                if m.get("tool_calls"):
                    chars += sum(len(str(tc)) for tc in m["tool_calls"])
                return chars

            _est_tokens = sum(_est_msg_chars(m) // 4 for m in messages)
            _wait = check_rate_limit(provider_id, _est_tokens)
            if _wait:
                logger.info("Provider TPM limit: waiting %ds before LLM call", _wait)
                yield _event_with_compaction_tag(
                    {"type": "rate_limit_wait", "wait_seconds": _wait, "provider_id": provider_id or ""},
                    compaction,
                )
                await asyncio.sleep(_wait)

            # --- Model elevation ---
            _elev_cfg = await get_elevation_config(bot, channel_id)
            if _elev_cfg.enabled and not compaction:
                decision = classify_turn(
                    messages, model,
                    _elev_cfg.elevated_model,
                    _elev_cfg.threshold,
                    tool_calls_made,
                )
                effective_model = decision.model
                _elev_log_id = await log_elevation(
                    decision, turn_id=correlation_id,
                    bot_id=bot.id, channel_id=channel_id,
                )
                if decision.was_elevated:
                    logger.info(
                        "Elevation: %s → %s (score=%.2f, rules=%s)",
                        model, effective_model, decision.score, decision.rules_fired,
                    )
            else:
                effective_model = model
                _elev_log_id = None

            messages = _sanitize_messages(messages)

            import time as _time
            _llm_t0 = _time.monotonic()

            # --- Streaming LLM call ---
            accumulated_msg: AccumulatedMessage | None = None
            async for item in _llm_call_stream(
                effective_model, messages, tools_param, tool_choice,
                provider_id=provider_id, model_params=bot.model_params,
                fallback_models=fallback_models,
            ):
                if isinstance(item, AccumulatedMessage):
                    accumulated_msg = item
                else:
                    yield _event_with_compaction_tag(item, compaction)

            _llm_latency_ms = int((_time.monotonic() - _llm_t0) * 1000)
            assert accumulated_msg is not None

            # Check if a fallback was used and emit trace event
            _fb_info = last_fallback_info.get()
            if _fb_info is not None:
                logger.warning(
                    "Fallback used: %s → %s (reason: %s)",
                    _fb_info.original_model, _fb_info.fallback_model, _fb_info.reason,
                )
                yield _event_with_compaction_tag({
                    "type": "fallback",
                    "original_model": _fb_info.original_model,
                    "fallback_model": _fb_info.fallback_model,
                    "reason": _fb_info.reason,
                }, compaction)
                if correlation_id is not None:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="model_fallback",
                        data={
                            "original_model": _fb_info.original_model,
                            "fallback_model": _fb_info.fallback_model,
                            "reason": _fb_info.reason,
                            "original_error": _fb_info.original_error,
                            "iteration": iteration + 1,
                        },
                        duration_ms=_llm_latency_ms,
                    ))

            # Backfill elevation log with outcome data
            if _elev_log_id is not None:
                _tokens = accumulated_msg.usage.total_tokens if accumulated_msg.usage else None
                asyncio.create_task(backfill_elevation_log(
                    _elev_log_id, tokens_used=_tokens, latency_ms=_llm_latency_ms,
                ))

            msg_dict = accumulated_msg.to_msg_dict()
            messages.append(msg_dict)

            if accumulated_msg.usage:
                logger.debug(
                    "Token usage: prompt=%d completion=%d total=%d",
                    accumulated_msg.usage.prompt_tokens,
                    accumulated_msg.usage.completion_tokens,
                    accumulated_msg.usage.total_tokens,
                )
                if correlation_id is not None:
                    _usage_data = {
                        "prompt_tokens": accumulated_msg.usage.prompt_tokens,
                        "completion_tokens": accumulated_msg.usage.completion_tokens,
                        "total_tokens": accumulated_msg.usage.total_tokens,
                        "iteration": iteration + 1,
                        "model": effective_model,
                        "provider_id": provider_id,
                        "channel_id": str(channel_id) if channel_id else None,
                    }
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="token_usage",
                        data=_usage_data,
                        duration_ms=_llm_latency_ms,
                    ))

            # Emit thinking content event for downstream consumers (Slack, etc.)
            if accumulated_msg.thinking_content:
                yield _event_with_compaction_tag(
                    {"type": "thinking_content", "text": accumulated_msg.thinking_content},
                    compaction,
                )

            if not accumulated_msg.tool_calls:
                text = accumulated_msg.content or ""
                _trace("✓ response (%d chars)", len(text))

                if not text.strip():
                    _empty_msg = (
                        f"LLM returned empty response after {iteration + 1} iteration(s) "
                        f"({len(tool_calls_made)} tool calls). Forcing retry."
                    )
                    logger.warning("LLM response was empty. Forcing a response...")
                    yield _event_with_compaction_tag({
                        "type": "warning",
                        "code": "empty_response",
                        "message": _empty_msg,
                    }, compaction)
                    # Remove the empty assistant message that was eagerly appended
                    # above — it would leak into persisted history as dead weight.
                    messages.pop()
                    messages.append({
                        "role": "system",
                        "content": "You must respond to the user. Write a response now."
                    })
                    try:
                        # Route through _llm_call so NO_SYSTEM_MESSAGE_PROVIDERS folding,
                        # retry logic, and fallback all apply.  Use tool_choice=none so we
                        # only get a plain assistant reply.
                        retry = await _llm_call(
                            model, messages,
                            tools_param,
                            "none" if tools_param is not None else None,
                            provider_id=provider_id,
                            fallback_models=fallback_models,
                        )
                        text = strip_think_tags(retry.choices[0].message.content or "")
                        messages.append(retry.choices[0].message.model_dump(exclude_none=True))
                    except Exception as exc:
                        logger.error("Forced-response retry failed: %s", exc)
                        if correlation_id is not None:
                            asyncio.create_task(_record_trace_event(
                                correlation_id=correlation_id,
                                session_id=session_id,
                                bot_id=bot.id,
                                client_id=client_id,
                                event_type="llm_error",
                                event_name="forced_response_retry",
                                data={"message": str(exc)[:2000]},
                            ))
                        text = f"[Error: {_empty_msg} Retry also failed: {type(exc).__name__}]"
                        messages.append({"role": "assistant", "content": text})
                        yield _event_with_compaction_tag({
                            "type": "error",
                            "code": "llm_error",
                            "message": text,
                        }, compaction)

                if native_audio and user_msg_index is not None and not transcript_emitted:
                    transcript, text = _extract_transcript(text)
                    messages[-1]["content"] = text
                    yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction)
                    if transcript:
                        logger.info("Audio transcript: %r", transcript[:100])
                        messages[user_msg_index] = {"role": "user", "content": transcript}
                    else:
                        logger.warning("Native audio response contained no transcript tags")
                        messages[user_msg_index] = {"role": "user", "content": "[inaudible]"}
                    transcript_emitted = True

                logger.info("Final response (%d chars): %r", len(text), text[:120])
                if correlation_id is not None and not compaction:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="response",
                        data={"text": text[:500], "full_length": len(text)},
                    ))

                # Fire after_response lifecycle hook (fire-and-forget)
                from app.agent.hooks import fire_hook, HookContext
                asyncio.create_task(fire_hook("after_response", HookContext(
                    bot_id=bot.id, session_id=session_id, channel_id=channel_id,
                    client_id=client_id, correlation_id=correlation_id,
                    extra={"response_length": len(text), "tool_calls_made": list(tool_calls_made)},
                )))

                yield _event_with_compaction_tag({
                    "type": "response",
                    "text": text,
                    "client_actions": (
                        _extract_client_actions(messages, turn_start) + embedded_client_actions
                    ),
                }, compaction)
                return

            _acc_content = accumulated_msg.content
            if native_audio and user_msg_index is not None and not transcript_emitted and _acc_content:
                transcript, _ = _extract_transcript(_acc_content)
                if transcript:
                    logger.info("Audio transcript (from tool-call response): %r", transcript[:100])
                    yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction)
                    messages[user_msg_index] = {"role": "user", "content": transcript}
                    transcript_emitted = True

            # Emit intermediate text when the LLM returns content alongside tool calls.
            # Without this, the text is recorded in conversation history but never
            # surfaces to streaming consumers (Slack, UI, etc.).
            _intermediate_text = (_acc_content or "").strip()
            if _intermediate_text:
                yield _event_with_compaction_tag(
                    {"type": "assistant_text", "text": _intermediate_text},
                    compaction,
                )

            _acc_tool_calls = accumulated_msg.tool_calls
            logger.info("LLM requested %d tool call(s)", len(_acc_tool_calls))

            for tc_idx, tc in enumerate(_acc_tool_calls):
                # Cancellation checkpoint: before each tool dispatch
                if session_id and session_locks.is_cancel_requested(session_id):
                    logger.info("Cancellation requested for session %s (before tool %s)", session_id, tc["function"]["name"])
                    # Append stub tool results for remaining tool calls to keep
                    # conversation history well-formed (assistant references these IDs).
                    for remaining_tc in _acc_tool_calls[tc_idx:]:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": remaining_tc["id"],
                            "content": "[Cancelled by user]",
                        })
                    yield _event_with_compaction_tag({"type": "cancelled"}, compaction)
                    return

                name = tc["function"]["name"]
                args = tc["function"]["arguments"]
                logger.info("Tool call: %s", name)
                logger.debug("Tool call %s args: %s", name, args)

                _trace("→ %s", name)
                yield _event_with_compaction_tag({"type": "tool_start", "tool": name, "args": args}, compaction)

                tc_result = await dispatch_tool_call(
                    name=name,
                    args=args,
                    tool_call_id=tc["id"],
                    bot_id=bot.id,
                    bot_memory=bot.memory,
                    session_id=session_id,
                    client_id=client_id,
                    correlation_id=correlation_id,
                    channel_id=channel_id,
                    iteration=iteration,
                    provider_id=provider_id,
                    summarize_enabled=_eff_summarize_enabled,
                    summarize_threshold=_eff_summarize_threshold,
                    summarize_model=_eff_summarize_model,
                    summarize_max_tokens=_eff_summarize_max_tokens,
                    summarize_exclude=_eff_summarize_exclude,
                    compaction=compaction,
                )

                # --- Approval gate ---
                if tc_result.needs_approval:
                    yield _event_with_compaction_tag({
                        "type": "approval_request",
                        "approval_id": tc_result.approval_id,
                        "tool": name,
                        "arguments": args,
                        "reason": tc_result.approval_reason,
                    }, compaction)
                    from app.agent.approval_pending import create_approval_pending
                    future = create_approval_pending(tc_result.approval_id)
                    try:
                        verdict = await asyncio.wait_for(future, timeout=tc_result.approval_timeout)
                    except asyncio.TimeoutError:
                        verdict = "expired"
                        # Mark DB record as expired
                        try:
                            from app.db.engine import async_session as _ap_session
                            from app.db.models import ToolApproval as _TA
                            async with _ap_session() as _ap_db:
                                _ap_row = await _ap_db.get(_TA, uuid.UUID(tc_result.approval_id))
                                if _ap_row and _ap_row.status == "pending":
                                    _ap_row.status = "expired"
                                    await _ap_db.commit()
                        except Exception:
                            logger.warning("Failed to mark approval %s as expired", tc_result.approval_id)
                    if verdict == "approved":
                        tc_result = await dispatch_tool_call(
                            name=name,
                            args=args,
                            tool_call_id=tc["id"],
                            bot_id=bot.id,
                            bot_memory=bot.memory,
                            session_id=session_id,
                            client_id=client_id,
                            correlation_id=correlation_id,
                            channel_id=channel_id,
                            iteration=iteration,
                            provider_id=provider_id,
                            summarize_enabled=_eff_summarize_enabled,
                            summarize_threshold=_eff_summarize_threshold,
                            summarize_model=_eff_summarize_model,
                            summarize_max_tokens=_eff_summarize_max_tokens,
                            summarize_exclude=_eff_summarize_exclude,
                            compaction=compaction,
                            skip_policy=True,
                        )
                    else:
                        tc_result.result_for_llm = json.dumps({"error": f"Tool call {verdict} by admin"})
                        tc_result.tool_event = {"type": "tool_result", "tool": name, "error": f"Tool call {verdict}"}
                    yield _event_with_compaction_tag({
                        "type": "approval_resolved",
                        "approval_id": tc_result.approval_id,
                        "verdict": verdict,
                    }, compaction)

                tool_calls_made.append(name)
                for pre_event in tc_result.pre_events:
                    yield pre_event
                if tc_result.embedded_client_action is not None:
                    embedded_client_actions.append(tc_result.embedded_client_action)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tc_result.result_for_llm,
                })
                yield _event_with_compaction_tag(tc_result.tool_event, compaction)

                # Fire after_tool_call lifecycle hook (fire-and-forget)
                from app.agent.hooks import fire_hook, HookContext
                asyncio.create_task(fire_hook("after_tool_call", HookContext(
                    bot_id=bot.id, session_id=session_id, channel_id=channel_id,
                    client_id=client_id, correlation_id=correlation_id,
                    extra={"tool_name": name, "tool_args": args, "duration_ms": tc_result.duration_ms},
                )))

        _max_iter_msg = (
            f"Max iterations reached ({effective_max_iterations} tool calls). "
            "Generating final response without tools."
        )
        logger.warning("Agent loop hit max iterations (%d)", effective_max_iterations)
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="warning",
                event_name="max_iterations",
                data={"iterations": effective_max_iterations, "message": _max_iter_msg},
            ))
        yield _event_with_compaction_tag({
            "type": "warning",
            "code": "max_iterations",
            "message": _max_iter_msg,
        }, compaction)

        messages.append({
            "role": "system",
            "content": "You have used too many tool calls. Please respond to the user now without using any tools.",
        })
        try:
            # Route through _llm_call so NO_SYSTEM_MESSAGE_PROVIDERS folding,
            # retry logic, and fallback all apply.
            response = await _llm_call(
                model, messages,
                tools_param,
                "none" if tools_param is not None else None,
                provider_id=provider_id,
                fallback_models=fallback_models,
            )
            msg = response.choices[0].message
        except Exception as exc:
            logger.error("Max-iterations final LLM call failed: %s", exc)
            _fallback_text = f"[Error: {_max_iter_msg} Final response generation also failed: {type(exc).__name__}]"
            messages.append({"role": "assistant", "content": _fallback_text})
            yield _event_with_compaction_tag({
                "type": "error",
                "code": "llm_error",
                "message": _fallback_text,
            }, compaction)
            yield _event_with_compaction_tag({
                "type": "response",
                "text": _fallback_text,
                "client_actions": (
                    _extract_client_actions(messages, turn_start) + embedded_client_actions
                ),
            }, compaction)
            return

        messages.append(msg.model_dump(exclude_none=True))
        if response.usage and correlation_id is not None:
            _usage_data2 = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
                "iteration": effective_max_iterations + 1,
                "model": model,
                "provider_id": provider_id,
                "channel_id": str(channel_id) if channel_id else None,
            }
            _resp_cost2 = getattr(response, '_hidden_params', {}).get('response_cost') if hasattr(response, '_hidden_params') else None
            if _resp_cost2 is None and hasattr(response, 'model_extra'):
                _hidden2 = (response.model_extra or {}).get('_hidden_params', {})
                if isinstance(_hidden2, dict):
                    _resp_cost2 = _hidden2.get('response_cost')
            if _resp_cost2 is not None:
                _usage_data2["response_cost"] = _resp_cost2
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="token_usage",
                data=_usage_data2,
            ))

        text = strip_think_tags(msg.content or "")
        if native_audio and user_msg_index is not None and not transcript_emitted:
            transcript, text = _extract_transcript(text)
            messages[-1]["content"] = text
            yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction)
            if transcript:
                messages[user_msg_index] = {"role": "user", "content": transcript}
            else:
                messages[user_msg_index] = {"role": "user", "content": "[inaudible]"}
            transcript_emitted = True

        _trace("✓ response (%d chars)", len(text))
        if correlation_id is not None and not compaction:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="response",
                data={"text": text[:500], "full_length": len(text)},
            ))

        # Fire after_response lifecycle hook (max-iterations path)
        from app.agent.hooks import fire_hook, HookContext
        asyncio.create_task(fire_hook("after_response", HookContext(
            bot_id=bot.id, session_id=session_id, channel_id=channel_id,
            client_id=client_id, correlation_id=correlation_id,
            extra={"response_length": len(text), "tool_calls_made": list(tool_calls_made)},
        )))

        yield _event_with_compaction_tag({
            "type": "response",
            "text": text,
            "client_actions": (
                _extract_client_actions(messages, turn_start) + embedded_client_actions
            ),
        }, compaction)

    except Exception as exc:
        # Fire after_response hook on error path so integrations can clean up
        # (e.g. Slack removes the hourglass reaction).
        try:
            from app.agent.hooks import fire_hook, HookContext
            asyncio.create_task(fire_hook("after_response", HookContext(
                bot_id=bot.id, session_id=session_id, channel_id=channel_id,
                client_id=client_id, correlation_id=correlation_id,
                extra={"error": True, "tool_calls_made": list(tool_calls_made)},
            )))
        except Exception:
            pass  # best-effort cleanup
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="error",
                event_name=type(exc).__name__,
                data={"traceback": traceback.format_exc()[:4000]},
            ))
        raise


async def run_stream(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
    attachments: list[dict] | None = None,
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    channel_id: uuid.UUID | None = None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
    fallback_models: list[dict] | None = None,
    injected_tools: list[dict] | None = None,
    system_preamble: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Core agent loop as an async generator that yields status events.

    Events:
      {"type": "tool_start", "tool": "<name>", "args": "<json>"}
      {"type": "tool_result", "tool": "<name>"}
      {"type": "assistant_text", "text": "..."}   (intermediate text alongside tool calls)
      {"type": "memory_context", "count": <int>}
      {"type": "transcript", "text": "..."}
      {"type": "delegation_post", "bot_id": "...", "text": "...", "reply_in_thread": bool}
      {"type": "response", "text": "...", "client_actions": [...]}

    delegation_post events are emitted just before the response event so that the Slack
    client can post child-bot messages first (giving them an earlier timestamp), then post
    the parent's response as a new message — ensuring correct visual ordering.
    """
    # Reset per-request embedding cache so identical queries across skills/memory/knowledge/tools
    # hit the cache instead of making redundant API calls.
    from app.agent.embeddings import clear_embed_cache
    clear_embed_cache()

    # Track whether this is the outermost run_stream invocation (not a nested call from
    # run_immediate).  Only the outermost instance manages the delegation-post queue;
    # nested calls (child runs inside delegate_to_agent) share the same list so their
    # queued posts bubble up to the outermost emitter.
    from app.agent.context import current_pending_delegation_posts
    _is_outermost_stream = current_pending_delegation_posts.get() is None
    _delegation_posts: list = []
    if _is_outermost_stream:
        current_pending_delegation_posts.set(_delegation_posts)
    else:
        # Reuse the outer list so deeply-nested delegation posts still reach the surface.
        _delegation_posts = current_pending_delegation_posts.get()  # type: ignore[assignment]

    set_agent_context(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot.id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        memory_cross_channel=bot.memory.cross_channel if bot.memory.enabled else None,
        memory_cross_client=bot.memory.cross_client if bot.memory.enabled else None,
        memory_cross_bot=bot.memory.cross_bot if bot.memory.enabled else None,
        memory_similarity_threshold=bot.memory.similarity_threshold if bot.memory.enabled else None,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
    )
    from app.agent.context import current_injected_tools
    current_injected_tools.set(injected_tools)
    native_audio = audio_data is not None
    turn_start = len(messages)

    assembly_result = AssemblyResult()
    async for event in assemble_context(
        messages=messages,
        bot=bot,
        user_message=user_message,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        audio_data=audio_data,
        audio_format=audio_format,
        attachments=attachments,
        native_audio=native_audio,
        result=assembly_result,
        system_preamble=system_preamble,
    ):
        yield event

    # --- RAG re-ranking ---
    from app.services.reranking import rerank_rag_context
    _rerank_result = await rerank_rag_context(
        messages, user_message,
        provider_id=provider_id_override or bot.model_provider_id,
    )
    if _rerank_result is not None:
        logger.info(
            "RAG re-rank: %d→%d chunks, %d→%d chars",
            _rerank_result.original_chunks, _rerank_result.kept_chunks,
            _rerank_result.original_chars, _rerank_result.kept_chars,
        )
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="rag_rerank",
                data={
                    "original_chunks": _rerank_result.original_chunks,
                    "kept_chunks": _rerank_result.kept_chunks,
                    "original_chars": _rerank_result.original_chars,
                    "kept_chars": _rerank_result.kept_chars,
                },
            ))
        yield {
            "type": "rag_rerank",
            "original_chunks": _rerank_result.original_chunks,
            "kept_chunks": _rerank_result.kept_chunks,
            "original_chars": _rerank_result.original_chars,
            "kept_chars": _rerank_result.kept_chars,
        }

    # Apply channel-level model override (lower priority than per-turn)
    if model_override is None and assembly_result.channel_model_override:
        model_override = assembly_result.channel_model_override
        provider_id_override = provider_id_override or assembly_result.channel_provider_id_override

    # Expose effective model/provider to tools (e.g. delegate_to_harness callback propagation)
    from app.agent.context import current_model_override, current_provider_id_override
    current_model_override.set(model_override)
    current_provider_id_override.set(provider_id_override)

    max_iterations_override = assembly_result.channel_max_iterations
    pre_selected_tools = assembly_result.pre_selected_tools
    user_msg_index = assembly_result.user_msg_index

    # Resolve fallback models: explicit override > channel list > bot list (global appended in _llm_call)
    _fallback_models = fallback_models if fallback_models is not None else (assembly_result.channel_fallback_models or bot.fallback_models or [])

    # Check usage limits before entering the agent loop
    from app.services.usage_limits import check_usage_limits, UsageLimitExceeded
    try:
        await check_usage_limits(model_override or bot.model, bot.id)
    except UsageLimitExceeded as exc:
        yield {"type": "error", "code": "usage_limit_exceeded", "message": str(exc)}
        return

    # Only the outermost run_stream buffers the response and emits delegation_post events.
    # Nested calls (child agents inside delegate_to_agent) just pass events through.
    if _is_outermost_stream:
        _last_response: dict | None = None
        async for event in run_agent_tool_loop(
            messages,
            bot,
            session_id=session_id,
            client_id=client_id,
            model_override=model_override,
            provider_id_override=provider_id_override,
            turn_start=turn_start,
            native_audio=native_audio,
            user_msg_index=user_msg_index,
            pre_selected_tools=pre_selected_tools,
            correlation_id=correlation_id,
            channel_id=channel_id,
            max_iterations=max_iterations_override,
            fallback_models=_fallback_models,
        ):
            if event.get("type") == "response":
                _last_response = event
            else:
                yield event
        # Emit child-bot delegation posts BEFORE the parent response so the Slack client
        # can post child messages first (lower Slack timestamp) then repost the parent.
        for _dp in _delegation_posts:
            yield {
                "type": "delegation_post",
                "bot_id": _dp["bot_id"],
                "text": _dp["text"],
                "reply_in_thread": _dp.get("reply_in_thread", False),
                "client_actions": _dp.get("client_actions", []),
            }
        if _last_response is not None:
            yield _last_response
    else:
        async for event in run_agent_tool_loop(
            messages,
            bot,
            session_id=session_id,
            client_id=client_id,
            model_override=model_override,
            provider_id_override=provider_id_override,
            turn_start=turn_start,
            native_audio=native_audio,
            user_msg_index=user_msg_index,
            pre_selected_tools=pre_selected_tools,
            correlation_id=correlation_id,
            channel_id=channel_id,
            max_iterations=max_iterations_override,
            fallback_models=_fallback_models,
        ):
            yield event


async def run(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
    attachments: list[dict] | None = None,
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    channel_id: uuid.UUID | None = None,
    model_override: str | None = None,
    provider_id_override: str | None = None,
    fallback_models: list[dict] | None = None,
    injected_tools: list[dict] | None = None,
    system_preamble: str | None = None,
) -> RunResult:
    """Non-streaming wrapper: runs the agent loop and returns the final result."""
    result = RunResult()
    _intermediate_texts: list[str] = []
    async for event in run_stream(
        messages, bot, user_message,
        session_id=session_id, client_id=client_id,
        audio_data=audio_data, audio_format=audio_format,
        attachments=attachments,
        correlation_id=correlation_id,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
        channel_id=channel_id,
        model_override=model_override,
        provider_id_override=provider_id_override,
        fallback_models=fallback_models,
        injected_tools=injected_tools,
        system_preamble=system_preamble,
    ):
        if event["type"] == "assistant_text":
            _intermediate_texts.append(event["text"])
        elif event["type"] == "response":
            # If the final response is empty but intermediate text was produced,
            # combine the intermediate messages as the result.
            final_text = event["text"]
            if not (final_text or "").strip() and _intermediate_texts:
                result.response = "\n\n".join(_intermediate_texts)
            else:
                result.response = final_text
            result.client_actions = event.get("client_actions", [])
        elif event["type"] == "transcript":
            result.transcript = event["text"]
        elif event["type"] == "delegation_post" and dispatch_type and dispatch_config:
            # Non-streaming context (task worker): deliver child bot's message via appropriate dispatcher.
            from app.services.delegation import delegation_service as _ds
            try:
                await _ds.post_child_response(
                    dispatch_type=dispatch_type,
                    dispatch_config=dispatch_config,
                    text=event.get("text", ""),
                    bot_id=event.get("bot_id") or "",
                    reply_in_thread=event.get("reply_in_thread", False),
                    client_actions=event.get("client_actions", []),
                )
            except Exception:
                logger.warning("run(): delegation_post failed for bot %s", event.get("bot_id"))
    return result
