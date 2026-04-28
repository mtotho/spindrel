import asyncio
import json
import logging
import time
import uuid

from app.utils import safe_create_task
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context
from app.services import session_locks
from app.agent.context_assembly import AssemblyResult, assemble_context
from app.agent.context_pruning import prune_in_loop_tool_results, should_prune_in_loop
from app.agent.loop_dispatch import (
    SummarizeSettings,
    resolve_approval_verdict,  # noqa: F401 — re-exported
    dispatch_iteration_tool_calls,
)
from app.agent.loop_helpers import (
    _CORRECTION_RE,  # noqa: F401 — re-exported
    _EMPTY_RESPONSE_GENERIC_FALLBACK,  # noqa: F401 — re-exported
    _append_transcript_text_entry,
    _append_transcript_tool_entry,  # noqa: F401 — re-exported
    _check_prompt_budget_guard,
    _collapse_final_assistant_tool_turn,  # noqa: F401 — re-exported
    _extract_last_user_text,  # noqa: F401 — re-exported
    _extract_usage_extras,  # noqa: F401 — re-exported
    _finalize_response,  # noqa: F401 — re-exported
    _handle_loop_exit_forced_response,
    _handle_no_tool_calls_path,
    _inject_opening_skill_nudges,
    _merge_activated_tools_into_param,
    _recover_tool_calls_from_text,
    _record_fallback_event,
    _resolve_effective_provider,  # noqa: F401 — re-exported
    _resolve_loop_config,
    _resolve_loop_tools,
    _sanitize_llm_text,
    _sanitize_messages,
    _synthesize_empty_response_fallback,  # noqa: F401 — re-exported
)
from app.agent.loop_exit import schedule_loop_error_cleanup, stream_loop_exit_finalization
from app.agent.loop_llm import LoopLlmIterationDone, stream_loop_llm_iteration
from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.loop_tool_iteration import LoopToolIterationDone, stream_loop_tool_iteration
from app.agent.message_utils import (
    _event_with_compaction_tag,
    _extract_client_actions,
    _extract_transcript,
    _merge_tool_schemas,
)
from app.agent.prompt_sizing import estimate_chars_to_tokens, message_prompt_chars
from app.agent.recording import _record_trace_event
from app.agent.llm import AccumulatedMessage, EmptyChoicesError, FallbackInfo, _llm_call, _llm_call_stream, _summarize_tool_result, extract_json_tool_calls, extract_xml_tool_calls, last_fallback_info, strip_malformed_tool_calls, strip_silent_tags, strip_think_tags  # noqa: F401 — re-exported
from app.agent.loop_cycle_detection import detect_cycle
from app.agent.tool_dispatch import dispatch_tool_call  # noqa: F401 — re-exported
from app.agent.tracing import _CLASSIFY_SYS_MSG, _SYS_MSG_PREFIXES, _trace  # noqa: F401 — re-exported
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas, is_client_tool  # noqa: F401 — re-exported
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas

logger = logging.getLogger(__name__)


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
    authorized_tool_names: set[str] | None = None,
    correlation_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    max_iterations: int | None = None,
    fallback_models: list[dict] | None = None,
    skip_tool_policy: bool = False,
    context_profile_name: str | None = None,
    run_control_policy: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Single agent tool loop: LLM + tool calls until final response. Caller builds messages and sets context.
    When compaction=True, every yielded event gets "compaction": True.
    """
    _loop_config = _resolve_loop_config(
        bot,
        max_iterations=max_iterations,
        model_override=model_override,
        provider_id_override=provider_id_override,
        context_profile_name=context_profile_name,
        settings_obj=settings,
    )
    effective_max_iterations = _loop_config.effective_max_iterations
    _max_iterations_source = _loop_config.max_iterations_source
    model = _loop_config.model
    provider_id = _loop_config.provider_id
    _effective_model_params = _loop_config.effective_model_params
    summarize_settings = _loop_config.summarize_settings
    _in_loop_keep_iterations = _loop_config.in_loop_keep_iterations

    _tool_state = await _resolve_loop_tools(
        bot,
        pre_selected_tools=pre_selected_tools,
        authorized_tool_names=authorized_tool_names,
        compaction=compaction,
        get_local_tool_schemas_fn=get_local_tool_schemas,
        fetch_mcp_tools_fn=fetch_mcp_tools,
        get_client_tool_schemas_fn=get_client_tool_schemas,
        merge_tool_schemas_fn=_merge_tool_schemas,
    )
    all_tools = _tool_state.all_tools
    tools_param = _tool_state.tools_param
    tool_choice = _tool_state.tool_choice
    _effective_allowed = _tool_state.effective_allowed
    _activated_list = _tool_state.activated_list
    _run_control_policy = run_control_policy or {}
    _soft_max_llm_calls = int(_run_control_policy.get("soft_max_llm_calls") or 0)
    _hard_max_llm_calls = int(_run_control_policy.get("hard_max_llm_calls") or 0)
    _soft_current_prompt_tokens = int(_run_control_policy.get("soft_current_prompt_tokens") or 0)
    _target_seconds = int(_run_control_policy.get("target_seconds") or 0)
    _run_started_at = time.monotonic()
    if _hard_max_llm_calls > 0:
        if context_profile_name == "heartbeat" and _max_iterations_source == "global":
            effective_max_iterations = _hard_max_llm_calls
        else:
            effective_max_iterations = min(effective_max_iterations, _hard_max_llm_calls)

    logger.debug("Tools available: %s", [t["function"]["name"] for t in all_tools] if all_tools else "(none)")

    if context_profile_name == "heartbeat":
        import json as _json
        _tool_schema_chars = sum(len(_json.dumps(t, default=str)) for t in (tools_param or []))
        _tool_surface_event = {
            "type": "tool_surface_summary",
            "context_profile": context_profile_name,
            "tool_count": len(tools_param or []),
            "tool_schema_tokens_estimate": estimate_chars_to_tokens(_tool_schema_chars),
            "tools": [(t.get("function") or {}).get("name") for t in (tools_param or [])],
            "tool_surface": _run_control_policy.get("tool_surface") or "unknown",
            "continuation_mode": _run_control_policy.get("continuation_mode") or "stateless",
            "max_iterations_source": _max_iterations_source,
            "effective_max_iterations": effective_max_iterations,
        }
        yield _event_with_compaction_tag(_tool_surface_event, compaction)
        if correlation_id is not None:
            safe_create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="tool_surface_summary",
                data={k: v for k, v in _tool_surface_event.items() if k != "type"},
            ))

    ctx = LoopRunContext(
        bot=bot,
        session_id=session_id,
        client_id=client_id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        compaction=compaction,
        native_audio=native_audio,
        user_msg_index=user_msg_index,
        turn_start=turn_start,
    )
    state = LoopRunState(
        messages=messages,
    )

    try:
        import time as _time
        from app.agent.hooks import fire_hook
        from app.services.providers import resolve_provider_for_model
        from app.services.secret_registry import redact as _redact_secrets

        # Resolve provider once — used for rate limiting AND the actual LLM call.
        effective_provider_id = provider_id
        if effective_provider_id is None:
            effective_provider_id = resolve_provider_for_model(model)

        # --- Opening-turn skill nudges (one-shot, before first LLM call) ---
        _has_manage_bot_skill = _tool_state.has_manage_bot_skill
        await _inject_opening_skill_nudges(
            bot=bot,
            messages=messages,
            has_manage_bot_skill=_has_manage_bot_skill,
            correlation_id=correlation_id,
        )

        for iteration in range(effective_max_iterations):
            # Cancellation checkpoint: before LLM call
            if session_id and session_locks.is_cancel_requested(session_id):
                logger.info("Cancellation requested for session %s (before LLM call, iteration %d)", session_id, iteration + 1)
                yield _event_with_compaction_tag({"type": "cancelled"}, compaction)
                return

            # Merge any tools activated mid-loop by get_tool_info into tools_param
            # so the LLM can actually invoke them on this iteration.
            tools_param, tool_choice = _merge_activated_tools_into_param(
                _activated_list,
                tools_param,
                tool_choice,
                _effective_allowed,
                iteration=iteration,
            )

            logger.debug("--- Iteration %d ---", iteration + 1)
            logger.debug("Calling LLM (%s) with %d messages", model, len(messages))

            # In-loop pruning: trim tool results from older iterations within
            # this turn. Runs only when live-history utilization crosses the
            # pressure threshold; below threshold, pruning is pure loss.
            if iteration > 0 and settings.IN_LOOP_PRUNING_ENABLED:
                _elapsed_seconds = time.monotonic() - _run_started_at
                _soft_budget_pressure = (
                    context_profile_name == "heartbeat"
                    and not state.soft_budget_slimmed
                    and (
                        (_soft_max_llm_calls > 0 and iteration >= _soft_max_llm_calls)
                        or (
                            _soft_current_prompt_tokens > 0
                            and state.current_prompt_tokens_total >= _soft_current_prompt_tokens
                        )
                        or (
                            _target_seconds > 0
                            and _elapsed_seconds >= _target_seconds
                        )
                    )
                )
                if _soft_budget_pressure:
                    _pressure_reason = "soft_max_llm_calls"
                    if _target_seconds > 0 and _elapsed_seconds >= _target_seconds:
                        _pressure_reason = "target_seconds"
                    elif (
                        _soft_current_prompt_tokens > 0
                        and state.current_prompt_tokens_total >= _soft_current_prompt_tokens
                    ):
                        _pressure_reason = "soft_current_prompt_tokens"
                    state.soft_budget_slimmed = True
                    _pressure_event = {
                        "type": "heartbeat_budget_pressure",
                        "iteration": iteration + 1,
                        "reason": _pressure_reason,
                        "soft_max_llm_calls": _soft_max_llm_calls or None,
                        "soft_current_prompt_tokens": _soft_current_prompt_tokens or None,
                        "current_prompt_tokens_total": state.current_prompt_tokens_total,
                        "target_seconds": _target_seconds or None,
                        "elapsed_seconds": round(_elapsed_seconds, 3),
                    }
                    yield _event_with_compaction_tag(_pressure_event, compaction)
                    if correlation_id is not None:
                        safe_create_task(_record_trace_event(
                            correlation_id=correlation_id,
                            session_id=session_id,
                            bot_id=bot.id,
                            client_id=client_id,
                            event_type="heartbeat_budget_pressure",
                            data={k: v for k, v in _pressure_event.items() if k != "type"},
                        ))
                    _in_loop_stats = prune_in_loop_tool_results(
                        messages,
                        keep_iterations=min(_in_loop_keep_iterations, 1),
                        min_content_length=settings.CONTEXT_PRUNING_MIN_LENGTH,
                    )
                    yield _event_with_compaction_tag({
                        "type": "context_pruning",
                        "pruned_count": _in_loop_stats["pruned_count"],
                        "chars_saved": _in_loop_stats["chars_saved"],
                        "iterations_pruned": _in_loop_stats["iterations_pruned"],
                        "tool_call_args_pruned": _in_loop_stats.get("tool_call_args_pruned", 0),
                        "tool_call_arg_chars_saved": _in_loop_stats.get("tool_call_arg_chars_saved", 0),
                        "scope": "in_loop",
                        "keep_iterations": min(_in_loop_keep_iterations, 1),
                        "live_history_utilization": None,
                        "triggered_by": "heartbeat_soft_budget",
                    }, compaction)
                    messages.append({
                        "role": "system",
                        "content": (
                            "Heartbeat soft budget reached. Continue only if one more tool call is clearly "
                            "high-value and novel; otherwise produce a concise final heartbeat result."
                        ),
                    })
                    if correlation_id is not None:
                        safe_create_task(_record_trace_event(
                            correlation_id=correlation_id,
                            session_id=session_id,
                            bot_id=bot.id,
                            client_id=client_id,
                            event_type="context_pruning",
                            count=_in_loop_stats["pruned_count"],
                            data={
                                "scope": "in_loop",
                                "chars_saved": _in_loop_stats["chars_saved"],
                                "iterations_pruned": _in_loop_stats["iterations_pruned"],
                                "tool_call_args_pruned": _in_loop_stats.get("tool_call_args_pruned", 0),
                                "tool_call_arg_chars_saved": _in_loop_stats.get("tool_call_arg_chars_saved", 0),
                                "iteration": iteration + 1,
                                "keep_iterations": min(_in_loop_keep_iterations, 1),
                                "triggered_by": "heartbeat_soft_budget",
                            },
                        ))
                    continue
                _available_budget_tokens = 0
                try:
                    from app.agent.context_budget import get_model_context_window
                    _window = get_model_context_window(model, effective_provider_id)
                    if _window > 0:
                        _available_budget_tokens = max(
                            0,
                            _window - int(_window * settings.CONTEXT_BUDGET_RESERVE_RATIO),
                        )
                except Exception:
                    _available_budget_tokens = 0

                _should_prune, _utilization = should_prune_in_loop(
                    messages,
                    available_budget_tokens=_available_budget_tokens,
                    pressure_threshold=settings.IN_LOOP_PRUNING_PRESSURE_THRESHOLD,
                )
                if _should_prune:
                    _in_loop_stats = prune_in_loop_tool_results(
                        messages,
                        keep_iterations=_in_loop_keep_iterations,
                        min_content_length=settings.CONTEXT_PRUNING_MIN_LENGTH,
                    )
                    if _in_loop_stats["pruned_count"] > 0 or _in_loop_stats.get("tool_call_args_pruned", 0) > 0:
                        logger.info(
                            "In-loop pruning: %d tool results pruned (saved %d chars) at iter %d (utilization=%.2f)",
                            _in_loop_stats["pruned_count"],
                            _in_loop_stats["chars_saved"],
                            iteration + 1,
                            _utilization,
                        )
                        yield _event_with_compaction_tag({
                            "type": "context_pruning",
                            "pruned_count": _in_loop_stats["pruned_count"],
                            "chars_saved": _in_loop_stats["chars_saved"],
                            "iterations_pruned": _in_loop_stats["iterations_pruned"],
                            "tool_call_args_pruned": _in_loop_stats.get("tool_call_args_pruned", 0),
                            "tool_call_arg_chars_saved": _in_loop_stats.get("tool_call_arg_chars_saved", 0),
                            "scope": "in_loop",
                            "keep_iterations": _in_loop_keep_iterations,
                            "live_history_utilization": _utilization,
                            "triggered_by": "pressure",
                        }, compaction)
                        if correlation_id is not None:
                            safe_create_task(_record_trace_event(
                                correlation_id=correlation_id,
                                session_id=session_id,
                                bot_id=bot.id,
                                client_id=client_id,
                                event_type="context_pruning",
                                count=_in_loop_stats["pruned_count"],
                                data={
                                    "scope": "in_loop",
                                    "chars_saved": _in_loop_stats["chars_saved"],
                                    "iterations_pruned": _in_loop_stats["iterations_pruned"],
                                    "tool_call_args_pruned": _in_loop_stats.get("tool_call_args_pruned", 0),
                                    "tool_call_arg_chars_saved": _in_loop_stats.get("tool_call_arg_chars_saved", 0),
                                    "iteration": iteration + 1,
                                    "keep_iterations": _in_loop_keep_iterations,
                                    "live_history_utilization": _utilization,
                                    "triggered_by": "pressure",
                                },
                            ))

            # Context breakdown trace (first iteration only — avoids O(n) scan every iteration)
            if correlation_id is not None and iteration == 0:
                _breakdown: dict[str, dict] = {}
                for _m in messages:
                    _role = _m.get("role", "?")
                    _content = _m.get("content") or ""
                    _chars = message_prompt_chars(_m)
                    _key = _role
                    if _role == "system" and isinstance(_content, str):
                        _key = _CLASSIFY_SYS_MSG(_content)
                    if _key not in _breakdown:
                        _breakdown[_key] = {"count": 0, "chars": 0}
                    _breakdown[_key]["count"] += 1
                    _breakdown[_key]["chars"] += _chars
                safe_create_task(_record_trace_event(
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

            # Prompt budget gate: context-window hard block + TPM rate-limit wait.
            _budget_gate = _check_prompt_budget_guard(
                messages=messages,
                tools_param=tools_param,
                model=model,
                effective_provider_id=effective_provider_id,
                iteration=iteration,
                correlation_id=correlation_id,
                session_id=session_id,
                bot=bot,
                client_id=client_id,
                turn_start=turn_start,
                embedded_client_actions=state.embedded_client_actions,
                compaction=compaction,
            )
            for _evt in _budget_gate.events:
                yield _evt
            if _budget_gate.should_return:
                return
            if _budget_gate.wait_seconds:
                await asyncio.sleep(_budget_gate.wait_seconds)

            _llm_done: LoopLlmIterationDone | None = None
            async for _llm_event in stream_loop_llm_iteration(
                ctx=ctx,
                state=state,
                iteration=iteration,
                model=model,
                tools_param=tools_param,
                tool_choice=tool_choice,
                effective_provider_id=effective_provider_id,
                model_params=_effective_model_params,
                fallback_models=fallback_models,
                session_lock_manager=session_locks,
                llm_call_stream_fn=_llm_call_stream,
                last_fallback_info_get_fn=last_fallback_info.get,
                fire_hook_fn=fire_hook,
                record_trace_event_fn=_record_trace_event,
                record_fallback_event_fn=_record_fallback_event,
                safe_create_task_fn=safe_create_task,
                monotonic_fn=_time.monotonic,
            ):
                if isinstance(_llm_event, LoopLlmIterationDone):
                    _llm_done = _llm_event
                    continue
                yield _llm_event
                if _llm_event.get("type") == "cancelled":
                    return
            if _llm_done is None:
                return

            accumulated_msg = _llm_done.accumulated_msg
            effective_model = _llm_done.effective_model
            messages = state.messages

            # Recover tool calls from JSON-in-text (local model compat) or
            # suppressed XML blocks (MiniMax and siblings emit <invoke> as text).
            _recover_tool_calls_from_text(
                accumulated_msg, messages, _effective_allowed,
            )

            if not accumulated_msg.tool_calls:
                async for _evt in _handle_no_tool_calls_path(
                    accumulated_msg=accumulated_msg,
                    ctx=ctx,
                    state=state,
                    iteration=iteration,
                    model=model,
                    tools_param=tools_param,
                    effective_provider_id=effective_provider_id,
                    fallback_models=fallback_models,
                    llm_call_fn=_llm_call,
                ):
                    yield _evt
                return

            _tool_iteration_done: LoopToolIterationDone | None = None
            async for _tool_iteration_event in stream_loop_tool_iteration(
                accumulated_msg=accumulated_msg,
                ctx=ctx,
                state=state,
                iteration=iteration,
                provider_id=effective_provider_id,
                model=model,
                summarize_settings=summarize_settings,
                skip_tool_policy=skip_tool_policy,
                effective_allowed=_effective_allowed,
                settings_obj=settings,
                session_lock_manager=session_locks,
                in_loop_keep_iterations=_in_loop_keep_iterations,
                has_manage_bot_skill=_has_manage_bot_skill,
                dispatch_iteration_tool_calls_fn=dispatch_iteration_tool_calls,
                dispatch_tool_call_fn=dispatch_tool_call,
                is_client_tool_fn=is_client_tool,
                redact_fn=_redact_secrets,
                prune_in_loop_tool_results_fn=prune_in_loop_tool_results,
                should_prune_in_loop_fn=should_prune_in_loop,
                detect_cycle_fn=detect_cycle,
            ):
                if isinstance(_tool_iteration_event, LoopToolIterationDone):
                    _tool_iteration_done = _tool_iteration_event
                    continue
                yield _tool_iteration_event
            if _tool_iteration_done is None or _tool_iteration_done.cancelled:
                return
            if _tool_iteration_done.break_loop:
                break

        # --- Post-loop: forced response (max iterations or cycle break) ---
        async for _evt in stream_loop_exit_finalization(
            ctx=ctx,
            state=state,
            iteration=iteration,
            effective_max_iterations=effective_max_iterations,
            tools_param=tools_param,
            model=model,
            effective_provider_id=effective_provider_id,
            fallback_models=fallback_models,
            llm_call_fn=_llm_call,
            handle_loop_exit_forced_response_fn=_handle_loop_exit_forced_response,
        ):
            yield _evt
        if state.terminated:
            return

    except Exception as exc:
        schedule_loop_error_cleanup(
            exc=exc,
            ctx=ctx,
            state=state,
            record_trace_event_fn=_record_trace_event,
            safe_create_task_fn=safe_create_task,
        )
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
    skip_tool_policy: bool = False,
    task_mode: bool = False,
    skip_skill_inject: bool = False,
    context_profile_name: str | None = None,
    run_control_policy: dict[str, Any] | None = None,
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

    # Reset per-request task creation counter
    from app.agent.context import task_creation_count
    task_creation_count.set(0)

    # Track whether this is the outermost run_stream invocation (not a nested call from
    # run_immediate).  Only the outermost instance manages the delegation-post queue;
    # nested calls (child runs inside delegate_to_agent) share the same list so their
    # queued posts bubble up to the outermost emitter.
    from app.agent.context import current_pending_delegation_posts, current_turn_responded_bots
    _is_outermost_stream = current_pending_delegation_posts.get() is None
    _delegation_posts: list = []
    if _is_outermost_stream:
        current_pending_delegation_posts.set(_delegation_posts)
        # Reset anti-loop tracker for this user turn
        current_turn_responded_bots.set({bot.id})
    else:
        # Reuse the outer list so deeply-nested delegation posts still reach the surface.
        _delegation_posts = current_pending_delegation_posts.get()  # type: ignore[assignment]

    set_agent_context(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot.id,
        correlation_id=correlation_id,
        channel_id=channel_id,
        memory_cross_channel=None,  # DB memory deprecated
        memory_cross_client=None,
        memory_cross_bot=None,
        memory_similarity_threshold=None,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
    )
    from app.agent.context import current_injected_tools
    current_injected_tools.set(injected_tools)
    native_audio = audio_data is not None
    turn_start = len(messages)

    # Channel-persisted `/effort` override. Read from channel.config once per
    # outermost turn and set the ContextVar so nested run_stream / delegation
    # children inherit via snapshot/restore. Nested calls skip the DB hit —
    # they read the ContextVar already set by the outermost caller.
    from app.agent.context import current_effort_override as _effort_ctx
    if _effort_ctx.get() is None and channel_id is not None:
        try:
            from app.db.engine import async_session as _effort_session_factory
            from app.db.models import Channel as _EffortChannel
            async with _effort_session_factory() as _effort_db:
                _ch = await _effort_db.get(_EffortChannel, channel_id)
                if _ch is not None:
                    _override = (_ch.config or {}).get("effort_override")
                    if _override in ("off", "low", "medium", "high"):
                        _effort_ctx.set(_override)
        except Exception:
            logger.debug("effort override lookup failed", exc_info=True)

    # Apply channel-level model/provider override before any provider-sensitive
    # prompt rendering or budget accounting. Context assembly still records the
    # channel settings in AssemblyResult, but the effective call parameters need
    # to be known before assembly starts.
    if model_override is None and channel_id is not None:
        try:
            from app.db.engine import async_session as _model_session_factory
            from app.db.models import Channel as _ModelChannel
            async with _model_session_factory() as _model_db:
                _ch = await _model_db.get(_ModelChannel, channel_id)
                if _ch is not None and _ch.model_override:
                    model_override = _ch.model_override
                    provider_id_override = provider_id_override or getattr(
                        _ch,
                        "model_provider_id_override",
                        None,
                    )
        except Exception:
            logger.debug("channel model override lookup failed", exc_info=True)

    from app.agent.context import current_run_origin
    from app.agent.context_profiles import resolve_context_profile

    _resolved_context_profile = context_profile_name
    if _resolved_context_profile is None:
        _origin = current_run_origin.get(None)
        _session = None
        if session_id is not None:
            try:
                from app.db.engine import async_session as _async_session
                from app.db.models import Session as _Session
                async with _async_session() as _profile_db:
                    _session = await _profile_db.get(_Session, session_id)
            except Exception:
                logger.debug("context profile session lookup failed", exc_info=True)
        _resolved_context_profile = resolve_context_profile(
            session=_session,
            origin=_origin,
        ).name

    # --- context budget ---
    _budget = None
    if settings.CONTEXT_BUDGET_ENABLED:
        from app.agent.context_budget import ContextBudget, get_model_context_window
        _effective_model = model_override or bot.model
        _effective_provider = _resolve_effective_provider(model_override, provider_id_override, bot.model_provider_id)
        _window = get_model_context_window(_effective_model, _effective_provider)
        _reserve_ratio = settings.CONTEXT_BUDGET_RESERVE_RATIO
        _budget = ContextBudget(
            total_tokens=_window,
            reserve_tokens=int(_window * _reserve_ratio),
        )

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
        budget=_budget,
        task_mode=task_mode,
        skip_skill_inject=skip_skill_inject,
        context_profile_name=_resolved_context_profile,
        model_override=model_override,
        provider_id_override=provider_id_override,
        tool_surface_policy=(run_control_policy or {}).get("tool_surface"),
    ):
        yield event

    # --- post-assembly: account for tool schemas in budget ---
    if _budget is not None and assembly_result.pre_selected_tools:
        import json as _json
        _tool_schema_chars = sum(len(_json.dumps(t)) for t in assembly_result.pre_selected_tools)
        from app.agent.context_budget import estimate_tokens as _est
        _budget.consume("tool_schemas", _est("x" * _tool_schema_chars))
        logger.debug("Budget after assembly: %s", _budget.to_dict())

    # Emit budget info event for downstream consumers (e.g. compaction trigger)
    if _budget is not None:
        _budget_dict = _budget.to_dict()
        _policy = assembly_result.context_policy or {}
        yield {
            "type": "context_budget",
            "utilization": round(_budget.utilization, 3),
            "total_tokens": _budget.total_tokens,
            "consumed_tokens": _budget.consumed_tokens,
            "remaining_tokens": _budget.remaining,
            "available_budget": _budget_dict["available_budget"],
            "base_tokens": _budget_dict["base_tokens"],
            "live_history_tokens": _budget_dict["live_history_tokens"],
            "live_history_utilization": _budget_dict["live_history_utilization"],
            "static_injection_tokens": _budget_dict["static_injection_tokens"],
            "tool_schema_tokens": _budget_dict["tool_schema_tokens"],
            "context_profile": _resolved_context_profile,
            "context_origin": assembly_result.context_origin,
            "live_history_turns": _policy.get("live_history_turns"),
            "mandatory_static_injections": _policy.get("mandatory_static_injections") or [],
            "optional_static_injections": _policy.get("optional_static_injections") or [],
        }

    # Surface skills-still-in-context for the UI "skill orb" on the persisted
    # assistant message. Sourced from conversation-history scan in assembly.
    if assembly_result.skills_in_context:
        yield {
            "type": "active_skills",
            "skills": assembly_result.skills_in_context,
        }

    # --- RAG re-ranking ---
    from app.services.reranking import rerank_rag_context
    _rerank_result = await rerank_rag_context(
        messages, user_message,
        provider_id=settings.RAG_RERANK_MODEL_PROVIDER_ID or _resolve_effective_provider(model_override, provider_id_override, bot.model_provider_id),
    )
    if _rerank_result is not None:
        logger.info(
            "RAG re-rank: %d→%d chunks, %d→%d chars",
            _rerank_result.original_chunks, _rerank_result.kept_chunks,
            _rerank_result.original_chars, _rerank_result.kept_chars,
        )
        if correlation_id is not None:
            safe_create_task(_record_trace_event(
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

    # --- auto-inject: synthetic get_skill() tool call/result pairs ---
    # When context assembly identified enrolled skills to auto-inject, emit
    # them as synthetic tool call/result pairs so the content persists in
    # conversation history (system messages are ephemeral and get filtered
    # out at persist time). This matches the shape of a real get_skill() call
    # so the content gets _no_prune protection and survives across turns.
    if assembly_result.auto_inject_skills:
        import hashlib as _hashlib
        from app.agent.context import current_skills_in_context
        _resident_skills = list(current_skills_in_context.get() or [])
        for _ai_skill in assembly_result.auto_inject_skills:
            _ai_sid = _ai_skill["skill_id"]
            _ai_tcid = f"auto_inject_{_hashlib.md5(_ai_sid.encode()).hexdigest()[:12]}"
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": _ai_tcid,
                    "type": "function",
                    "function": {
                        "name": "get_skill",
                        "arguments": json.dumps({"skill_id": _ai_sid}),
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": _ai_tcid,
                "content": _ai_skill["content"],
                "_no_prune": True,
                "_auto_inject": True,
            })
            if not any(
                isinstance(_entry, dict) and _entry.get("skill_id") == _ai_sid
                for _entry in _resident_skills
            ):
                _resident_skills.insert(0, {
                    "skill_id": _ai_sid,
                    "skill_name": _ai_skill["content"].splitlines()[0].removeprefix("# ").strip() or _ai_sid,
                    "source": "auto_injected",
                    "messages_ago": 0,
                })
        current_skills_in_context.set(_resident_skills)
        logger.info(
            "Auto-injected %d skill(s) as synthetic get_skill() pairs: %s",
            len(assembly_result.auto_inject_skills),
            [s["skill_id"] for s in assembly_result.auto_inject_skills],
        )

    # Apply channel-level model override (lower priority than per-turn)
    if model_override is None and assembly_result.channel_model_override:
        model_override = assembly_result.channel_model_override
        provider_id_override = provider_id_override or assembly_result.channel_provider_id_override

    # Expose effective model/provider to tools (e.g. delegation callback propagation)
    from app.agent.context import current_model_override, current_provider_id_override, current_channel_model_tier_overrides
    current_model_override.set(model_override)
    current_provider_id_override.set(provider_id_override)
    # Expose channel tier overrides to delegation tools (always set to avoid staleness)
    current_channel_model_tier_overrides.set(assembly_result.channel_model_tier_overrides)

    max_iterations_override = assembly_result.channel_max_iterations
    pre_selected_tools = assembly_result.pre_selected_tools
    _authorized_tool_names = assembly_result.authorized_tool_names
    user_msg_index = assembly_result.user_msg_index

    # Apply tool injections from context assembly (memory scheme, channel workspace)
    # so the tool loop sees the full tool list even when tool_retrieval=false.
    if assembly_result.effective_local_tools and list(bot.local_tools) != assembly_result.effective_local_tools:
        from dataclasses import replace as _dc_replace
        bot = _dc_replace(bot, local_tools=assembly_result.effective_local_tools)

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
            authorized_tool_names=_authorized_tool_names,
            correlation_id=correlation_id,
            channel_id=channel_id,
            max_iterations=max_iterations_override,
            fallback_models=_fallback_models,
            skip_tool_policy=skip_tool_policy,
            context_profile_name=_resolved_context_profile,
            run_control_policy=run_control_policy,
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
        # Signal the UI to poll for async results (deferred delegations,
        # scheduled tasks, etc.) that will arrive after the stream closes.
        _pending = task_creation_count.get(0)
        if _pending > 0:
            yield {"type": "pending_tasks", "count": _pending}
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
            authorized_tool_names=_authorized_tool_names,
            correlation_id=correlation_id,
            channel_id=channel_id,
            max_iterations=max_iterations_override,
            fallback_models=_fallback_models,
            skip_tool_policy=skip_tool_policy,
            context_profile_name=_resolved_context_profile,
            run_control_policy=run_control_policy,
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
    skip_tool_policy: bool = False,
    task_mode: bool = False,
    skip_skill_inject: bool = False,
    context_profile_name: str | None = None,
    run_control_policy: dict[str, Any] | None = None,
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
        skip_tool_policy=skip_tool_policy,
        task_mode=task_mode,
        skip_skill_inject=skip_skill_inject,
        context_profile_name=context_profile_name,
        run_control_policy=run_control_policy,
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
        elif event["type"] == "delegation_post" and channel_id is not None:
            # Non-streaming context (task worker): publish child bot's
            # message onto the channel-events bus. Renderers consume the
            # NEW_MESSAGE event and post to the integration.
            from app.services.delegation import delegation_service as _ds
            try:
                await _ds.post_child_response(
                    channel_id=channel_id,
                    text=event.get("text", ""),
                    bot_id=event.get("bot_id") or "",
                    reply_in_thread=event.get("reply_in_thread", False),
                )
            except Exception:
                logger.warning("run(): delegation_post failed for bot %s", event.get("bot_id"))
    return result
