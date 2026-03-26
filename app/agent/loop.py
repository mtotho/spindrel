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
from app.agent.llm import EmptyChoicesError, _llm_call, _summarize_tool_result  # noqa: F401 — re-exported
from app.agent.tool_dispatch import dispatch_tool_call
from app.agent.tracing import _CLASSIFY_SYS_MSG, _SYS_MSG_PREFIXES, _trace  # noqa: F401 — re-exported
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas

logger = logging.getLogger(__name__)


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Ensure no message has null/missing content — some models reject it."""
    out = []
    for m in messages:
        if "content" not in m or m["content"] is None:
            m = {**m, "content": ""}
        out.append(m)
    return out


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
        if bot.workspace.enabled:
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
    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    logger.debug("Tools available: %s", [t["function"]["name"] for t in all_tools] if all_tools else "(none)")

    transcript_emitted = False
    embedded_client_actions: list[dict] = []
    tool_calls_made: list[str] = []  # track tool names for elevation classifier

    try:
        for iteration in range(effective_max_iterations):
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
            _est_tokens = sum(
                len(str(m.get("content") or "")) // 4 for m in messages
            )
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
            response = await _llm_call(effective_model, messages, tools_param, tool_choice, provider_id=provider_id, model_params=bot.model_params)
            _llm_latency_ms = int((_time.monotonic() - _llm_t0) * 1000)

            # Backfill elevation log with outcome data
            if _elev_log_id is not None:
                _tokens = response.usage.total_tokens if response.usage else None
                asyncio.create_task(backfill_elevation_log(
                    _elev_log_id, tokens_used=_tokens, latency_ms=_llm_latency_ms,
                ))

            msg = response.choices[0].message
            msg_dict = msg.model_dump(exclude_none=True)
            messages.append(msg_dict)

            if response.usage:
                logger.debug(
                    "Token usage: prompt=%d completion=%d total=%d",
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                    response.usage.total_tokens,
                )
                if correlation_id is not None:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="token_usage",
                        data={
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                            "total_tokens": response.usage.total_tokens,
                            "iteration": iteration + 1,
                            "model": effective_model,
                        },
                        duration_ms=_llm_latency_ms,
                    ))

            if not msg.tool_calls:
                text = msg.content or ""
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
                    messages.append({
                        "role": "system",
                        "content": "You must respond to the user. Write a response now."
                    })
                    try:
                        # Anthropic (via LiteLLM) rejects requests that include tool turns in
                        # `messages` unless `tools=` is also sent; use tool_choice=none so we
                        # only get a plain assistant reply.
                        retry_kw: dict[str, Any] = {"model": model, "messages": messages}
                        if tools_param is not None:
                            retry_kw["tools"] = tools_param
                            retry_kw["tool_choice"] = "none"
                        from app.services.providers import get_llm_client as _get_client
                        retry = await _get_client(provider_id).chat.completions.create(**retry_kw)
                        text = retry.choices[0].message.content or ""
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
                yield _event_with_compaction_tag({
                    "type": "response",
                    "text": text,
                    "client_actions": (
                        _extract_client_actions(messages, turn_start) + embedded_client_actions
                    ),
                }, compaction)
                return

            if native_audio and user_msg_index is not None and not transcript_emitted and msg.content:
                transcript, _ = _extract_transcript(msg.content)
                if transcript:
                    logger.info("Audio transcript (from tool-call response): %r", transcript[:100])
                    yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction)
                    messages[user_msg_index] = {"role": "user", "content": transcript}
                    transcript_emitted = True

            # Emit intermediate text when the LLM returns content alongside tool calls.
            # Without this, the text is recorded in conversation history but never
            # surfaces to streaming consumers (Slack, UI, etc.).
            _intermediate_text = (msg.content or "").strip()
            if _intermediate_text:
                yield _event_with_compaction_tag(
                    {"type": "assistant_text", "text": _intermediate_text},
                    compaction,
                )

            logger.info("LLM requested %d tool call(s)", len(msg.tool_calls))

            for tc in msg.tool_calls:
                name = tc.function.name
                args = tc.function.arguments
                logger.info("Tool call: %s", name)
                logger.debug("Tool call %s args: %s", name, args)

                _trace("→ %s", name)
                yield _event_with_compaction_tag({"type": "tool_start", "tool": name, "args": args}, compaction)

                tc_result = await dispatch_tool_call(
                    name=name,
                    args=args,
                    tool_call_id=tc.id,
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

                tool_calls_made.append(name)
                for pre_event in tc_result.pre_events:
                    yield pre_event
                if tc_result.embedded_client_action is not None:
                    embedded_client_actions.append(tc_result.embedded_client_action)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tc_result.result_for_llm,
                })
                yield _event_with_compaction_tag(tc_result.tool_event, compaction)

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
        final_kw: dict[str, Any] = {"model": model, "messages": messages}
        if tools_param is not None:
            final_kw["tools"] = tools_param
            final_kw["tool_choice"] = "none"
        from app.services.providers import get_llm_client as _get_client
        try:
            response = await _get_client(provider_id).chat.completions.create(**final_kw)
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
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="token_usage",
                data={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "iteration": effective_max_iterations + 1,
                    "model": model,
                },
            ))

        text = msg.content or ""
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
        yield _event_with_compaction_tag({
            "type": "response",
            "text": text,
            "client_actions": (
                _extract_client_actions(messages, turn_start) + embedded_client_actions
            ),
        }, compaction)

    except Exception as exc:
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
    ):
        yield event

    # Apply channel-level model override (lower priority than per-turn)
    if model_override is None and assembly_result.channel_model_override:
        model_override = assembly_result.channel_model_override
        provider_id_override = provider_id_override or assembly_result.channel_provider_id_override

    max_iterations_override = assembly_result.channel_max_iterations
    pre_selected_tools = assembly_result.pre_selected_tools
    user_msg_index = assembly_result.user_msg_index

    # --- Auto-summarize on resume after idle ---
    if channel_id:
        try:
            from app.services.summarizer import get_last_user_message_time, summarize_messages
            from app.db.models import Channel as _ChannelModel
            from app.db.engine import async_session as _async_session
            from sqlalchemy import select as _sel

            async with _async_session() as _db:
                _ch = (await _db.execute(
                    _sel(_ChannelModel).where(_ChannelModel.id == channel_id)
                )).scalar_one_or_none()

            if _ch and _ch.summarizer_enabled:
                _threshold = _ch.summarizer_threshold_minutes or settings.SUMMARIZER_THRESHOLD_MINUTES
                _last_ts = await get_last_user_message_time(channel_id)
                if _last_ts is not None:
                    _idle_minutes = (datetime.now(timezone.utc) - _last_ts).total_seconds() / 60
                    if _idle_minutes > _threshold:
                        _msg_count = _ch.summarizer_message_count or settings.SUMMARIZER_MESSAGE_COUNT
                        _summary = await summarize_messages(
                            channel_id=channel_id,
                            take=_msg_count,
                            provider_id=provider_id_override or bot.model_provider_id,
                        )
                        if _summary and not _summary.startswith("Error:"):
                            _auto_msg = (
                                f"[Auto-summary of prior conversation — last activity "
                                f"was {int(_idle_minutes)} minutes ago]\n\n{_summary}"
                            )
                            messages.insert(turn_start, {"role": "system", "content": _auto_msg})
                            turn_start += 1
                            if user_msg_index is not None:
                                user_msg_index += 1

                            if correlation_id is not None:
                                asyncio.create_task(_record_trace_event(
                                    correlation_id=correlation_id,
                                    session_id=session_id,
                                    bot_id=bot.id,
                                    client_id=client_id,
                                    event_type="auto_summarize",
                                    data={"idle_minutes": int(_idle_minutes), "summary_len": len(_summary)},
                                ))
                            yield {"type": "trace", "event_type": "auto_summarize", "idle_minutes": int(_idle_minutes)}
        except Exception:
            logger.warning("Auto-summarize failed, continuing without", exc_info=True)

    # --- Context compression (pre-turn) ---
    _compression_active = False
    _full_messages: list[dict] | None = None
    _pre_loop_len = 0
    loop_messages = messages
    loop_turn_start = turn_start
    loop_user_msg_index = user_msg_index

    from app.services.compression import compress_context
    from app.agent.context import set_compression_history
    _comp_result = await compress_context(
        messages, bot, user_message,
        channel_id=channel_id,
        provider_id=provider_id_override or bot.model_provider_id,
    )
    if _comp_result is not None:
        _compressed, _drilldown = _comp_result
        _compression_active = True
        _full_messages = list(messages)
        set_compression_history(session_id, _drilldown)
        existing_names = {t.get("function", {}).get("name") for t in (pre_selected_tools or [])}
        if "get_message_detail" not in existing_names:
            detail_schema = get_local_tool_schemas(["get_message_detail"])
            pre_selected_tools = (pre_selected_tools or []) + detail_schema

        _original_chars = sum(len(str(m.get("content", ""))) for m in messages)
        _compressed_chars = sum(len(str(m.get("content", ""))) for m in _compressed)

        loop_messages = _compressed
        _pre_loop_len = len(_compressed)
        loop_turn_start = _pre_loop_len
        # Recalculate user_msg_index for compressed list (needed for native audio)
        if user_msg_index is not None:
            loop_user_msg_index = None
            for _ci in range(len(_compressed) - 1, -1, -1):
                if _compressed[_ci].get("role") == "user":
                    loop_user_msg_index = _ci
                    break

        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="context_compressed",
                data={
                    "original_chars": _original_chars,
                    "compressed_chars": _compressed_chars,
                    "original_messages": len(messages),
                    "compressed_messages": len(_compressed),
                },
            ))
        yield {"type": "context_compressed", "original_chars": _original_chars, "compressed_chars": _compressed_chars}

    # Only the outermost run_stream buffers the response and emits delegation_post events.
    # Nested calls (child agents inside delegate_to_agent) just pass events through.
    if _is_outermost_stream:
        _last_response: dict | None = None
        async for event in run_agent_tool_loop(
            loop_messages,
            bot,
            session_id=session_id,
            client_id=client_id,
            model_override=model_override,
            provider_id_override=provider_id_override,
            turn_start=loop_turn_start,
            native_audio=native_audio,
            user_msg_index=loop_user_msg_index,
            pre_selected_tools=pre_selected_tools,
            correlation_id=correlation_id,
            channel_id=channel_id,
            max_iterations=max_iterations_override,
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
            loop_messages,
            bot,
            session_id=session_id,
            client_id=client_id,
            model_override=model_override,
            provider_id_override=provider_id_override,
            turn_start=loop_turn_start,
            native_audio=native_audio,
            user_msg_index=loop_user_msg_index,
            pre_selected_tools=pre_selected_tools,
            correlation_id=correlation_id,
            channel_id=channel_id,
            max_iterations=max_iterations_override,
        ):
            yield event

    # Restore original messages if compression was active — ensures persist_turn()
    # sees full history + new turn messages (not the compressed view).
    if _compression_active and _full_messages is not None:
        new_msgs = loop_messages[_pre_loop_len:]
        messages.clear()
        messages.extend(_full_messages)
        messages.extend(new_msgs)
        set_compression_history(session_id, None)


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
