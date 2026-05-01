import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.message_utils import _event_with_compaction_tag

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopPreLlmIterationDone:
    tools_param: list[dict[str, Any]] | None
    tool_choice: str | None
    return_loop: bool = False
    continue_loop: bool = False


async def stream_loop_pre_llm_iteration(
    *,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    model: str,
    effective_provider_id: str | None,
    tools_param: list[dict[str, Any]] | None,
    tool_choice: str | None,
    activated_list: list[dict],
    effective_allowed: set[str] | None,
    context_profile_name: str | None,
    run_started_at: float,
    soft_max_llm_calls: int,
    soft_current_prompt_tokens: int,
    target_seconds: int,
    in_loop_keep_iterations: int,
    settings_obj: Any,
    session_lock_manager: Any,
    merge_activated_tools_fn: Any,
    prune_in_loop_tool_results_fn: Any,
    should_prune_in_loop_fn: Any,
    check_prompt_budget_guard_fn: Any,
    record_trace_event_fn: Any,
    safe_create_task_fn: Any,
    sleep_fn: Any = asyncio.sleep,
    monotonic_fn: Any | None = None,
    message_prompt_chars_fn: Any | None = None,
    classify_sys_msg_fn: Any | None = None,
    get_model_context_window_fn: Any | None = None,
) -> AsyncGenerator[dict[str, Any] | LoopPreLlmIterationDone, None]:
    """Run pre-LLM controls for one loop iteration."""
    if ctx.session_id and session_lock_manager.is_cancel_requested(ctx.session_id):
        logger.info(
            "Cancellation requested for session %s (before LLM call, iteration %d)",
            ctx.session_id,
            iteration + 1,
        )
        yield _event_with_compaction_tag({"type": "cancelled"}, ctx.compaction)
        yield LoopPreLlmIterationDone(
            tools_param=tools_param,
            tool_choice=tool_choice,
            return_loop=True,
        )
        return

    tools_param, tool_choice = merge_activated_tools_fn(
        activated_list,
        tools_param,
        tool_choice,
        effective_allowed,
        iteration=iteration,
    )

    logger.debug("--- Iteration %d ---", iteration + 1)
    logger.debug("Calling LLM (%s) with %d messages", model, len(state.messages))

    if iteration > 0 and settings_obj.IN_LOOP_PRUNING_ENABLED:
        async for pruning_event in _stream_pre_llm_pruning(
            ctx=ctx,
            state=state,
            iteration=iteration,
            model=model,
            effective_provider_id=effective_provider_id,
            context_profile_name=context_profile_name,
            run_started_at=run_started_at,
            soft_max_llm_calls=soft_max_llm_calls,
            soft_current_prompt_tokens=soft_current_prompt_tokens,
            target_seconds=target_seconds,
            in_loop_keep_iterations=in_loop_keep_iterations,
            settings_obj=settings_obj,
            prune_in_loop_tool_results_fn=prune_in_loop_tool_results_fn,
            should_prune_in_loop_fn=should_prune_in_loop_fn,
            record_trace_event_fn=record_trace_event_fn,
            safe_create_task_fn=safe_create_task_fn,
            monotonic_fn=monotonic_fn,
            get_model_context_window_fn=get_model_context_window_fn,
            tools_param=tools_param,
        ):
            if isinstance(pruning_event, LoopPreLlmIterationDone):
                yield LoopPreLlmIterationDone(
                    tools_param=pruning_event.tools_param,
                    tool_choice=pruning_event.tool_choice,
                    continue_loop=pruning_event.continue_loop,
                    return_loop=pruning_event.return_loop,
                )
                return
            yield pruning_event

    _emit_context_breakdown_trace(
        ctx=ctx,
        state=state,
        iteration=iteration,
        record_trace_event_fn=record_trace_event_fn,
        safe_create_task_fn=safe_create_task_fn,
        message_prompt_chars_fn=message_prompt_chars_fn,
        classify_sys_msg_fn=classify_sys_msg_fn,
    )

    budget_gate = check_prompt_budget_guard_fn(
        messages=state.messages,
        tools_param=tools_param,
        model=model,
        effective_provider_id=effective_provider_id,
        iteration=iteration,
        correlation_id=ctx.correlation_id,
        session_id=ctx.session_id,
        bot=ctx.bot,
        client_id=ctx.client_id,
        turn_start=ctx.turn_start,
        embedded_client_actions=state.embedded_client_actions,
        compaction=ctx.compaction,
    )
    for event in budget_gate.events:
        yield event
    if budget_gate.should_return:
        yield LoopPreLlmIterationDone(
            tools_param=tools_param,
            tool_choice=tool_choice,
            return_loop=True,
        )
        return
    if budget_gate.wait_seconds:
        await sleep_fn(budget_gate.wait_seconds)

    yield LoopPreLlmIterationDone(
        tools_param=tools_param,
        tool_choice=tool_choice,
    )


async def _stream_pre_llm_pruning(
    *,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    model: str,
    effective_provider_id: str | None,
    context_profile_name: str | None,
    run_started_at: float,
    soft_max_llm_calls: int,
    soft_current_prompt_tokens: int,
    target_seconds: int,
    in_loop_keep_iterations: int,
    settings_obj: Any,
    prune_in_loop_tool_results_fn: Any,
    should_prune_in_loop_fn: Any,
    record_trace_event_fn: Any,
    safe_create_task_fn: Any,
    monotonic_fn: Any | None,
    get_model_context_window_fn: Any | None,
    tools_param: list[dict[str, Any]] | None,
) -> AsyncGenerator[dict[str, Any] | LoopPreLlmIterationDone, None]:
    messages = state.messages
    now = monotonic_fn if monotonic_fn is not None else time.monotonic
    elapsed_seconds = now() - run_started_at
    soft_budget_pressure = (
        context_profile_name == "heartbeat"
        and not state.soft_budget_slimmed
        and (
            (soft_max_llm_calls > 0 and iteration >= soft_max_llm_calls)
            or (
                soft_current_prompt_tokens > 0
                and state.current_prompt_tokens_total >= soft_current_prompt_tokens
            )
            or (target_seconds > 0 and elapsed_seconds >= target_seconds)
        )
    )
    if soft_budget_pressure:
        pressure_reason = "soft_max_llm_calls"
        if target_seconds > 0 and elapsed_seconds >= target_seconds:
            pressure_reason = "target_seconds"
        elif (
            soft_current_prompt_tokens > 0
            and state.current_prompt_tokens_total >= soft_current_prompt_tokens
        ):
            pressure_reason = "soft_current_prompt_tokens"
        state.soft_budget_slimmed = True
        pressure_event = {
            "type": "heartbeat_budget_pressure",
            "iteration": iteration + 1,
            "reason": pressure_reason,
            "soft_max_llm_calls": soft_max_llm_calls or None,
            "soft_current_prompt_tokens": soft_current_prompt_tokens or None,
            "current_prompt_tokens_total": state.current_prompt_tokens_total,
            "target_seconds": target_seconds or None,
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
        yield _event_with_compaction_tag(pressure_event, ctx.compaction)
        if ctx.correlation_id is not None:
            safe_create_task_fn(record_trace_event_fn(
                correlation_id=ctx.correlation_id,
                session_id=ctx.session_id,
                bot_id=ctx.bot.id,
                client_id=ctx.client_id,
                event_type="heartbeat_budget_pressure",
                data={k: v for k, v in pressure_event.items() if k != "type"},
            ))
        stats = prune_in_loop_tool_results_fn(
            messages,
            keep_iterations=min(in_loop_keep_iterations, 1),
            min_content_length=settings_obj.CONTEXT_PRUNING_MIN_LENGTH,
        )
        yield _event_with_compaction_tag({
            "type": "context_pruning",
            "pruned_count": stats["pruned_count"],
            "chars_saved": stats["chars_saved"],
            "iterations_pruned": stats["iterations_pruned"],
            "tool_call_args_pruned": stats.get("tool_call_args_pruned", 0),
            "tool_call_arg_chars_saved": stats.get("tool_call_arg_chars_saved", 0),
            "scope": "in_loop",
            "keep_iterations": min(in_loop_keep_iterations, 1),
            "live_history_utilization": None,
            "triggered_by": "heartbeat_soft_budget",
        }, ctx.compaction)
        messages.append({
            "role": "system",
            "content": (
                "Heartbeat soft budget reached. Tool use is now disabled for this turn; "
                "produce a concise final heartbeat result from the information already gathered."
            ),
        })
        if ctx.correlation_id is not None:
            safe_create_task_fn(record_trace_event_fn(
                correlation_id=ctx.correlation_id,
                session_id=ctx.session_id,
                bot_id=ctx.bot.id,
                client_id=ctx.client_id,
                event_type="context_pruning",
                count=stats["pruned_count"],
                data={
                    "scope": "in_loop",
                    "chars_saved": stats["chars_saved"],
                    "iterations_pruned": stats["iterations_pruned"],
                    "tool_call_args_pruned": stats.get("tool_call_args_pruned", 0),
                    "tool_call_arg_chars_saved": stats.get("tool_call_arg_chars_saved", 0),
                    "iteration": iteration + 1,
                    "keep_iterations": min(in_loop_keep_iterations, 1),
                    "triggered_by": "heartbeat_soft_budget",
                },
            ))
        yield LoopPreLlmIterationDone(
            tools_param=None,
            tool_choice="none",
        )
        return

    available_budget_tokens = 0
    try:
        if get_model_context_window_fn is None:
            from app.agent.context_budget import get_model_context_window as get_model_context_window_fn
        window = get_model_context_window_fn(model, effective_provider_id)
        if window > 0:
            available_budget_tokens = max(
                0,
                window - int(window * settings_obj.CONTEXT_BUDGET_RESERVE_RATIO),
            )
    except Exception:
        available_budget_tokens = 0

    tool_schema_tokens = 0
    if tools_param:
        try:
            from app.agent.context_budget import estimate_tokens

            tool_schema_chars = sum(len(json.dumps(t, default=str)) for t in tools_param)
            tool_schema_tokens = estimate_tokens("x" * tool_schema_chars)
        except Exception:
            tool_schema_tokens = 0
    should_prune, utilization = should_prune_in_loop_fn(
        messages,
        available_budget_tokens=available_budget_tokens,
        pressure_threshold=settings_obj.IN_LOOP_PRUNING_PRESSURE_THRESHOLD,
        tool_schema_tokens=tool_schema_tokens,
    )
    if not should_prune:
        return

    stats = prune_in_loop_tool_results_fn(
        messages,
        keep_iterations=in_loop_keep_iterations,
        min_content_length=settings_obj.CONTEXT_PRUNING_MIN_LENGTH,
    )
    if stats["pruned_count"] <= 0 and stats.get("tool_call_args_pruned", 0) <= 0:
        return

    logger.info(
        "In-loop pruning: %d tool results pruned (saved %d chars) at iter %d (utilization=%.2f)",
        stats["pruned_count"],
        stats["chars_saved"],
        iteration + 1,
        utilization,
    )
    yield _event_with_compaction_tag({
        "type": "context_pruning",
        "pruned_count": stats["pruned_count"],
        "chars_saved": stats["chars_saved"],
        "iterations_pruned": stats["iterations_pruned"],
        "tool_call_args_pruned": stats.get("tool_call_args_pruned", 0),
        "tool_call_arg_chars_saved": stats.get("tool_call_arg_chars_saved", 0),
        "scope": "in_loop",
        "keep_iterations": in_loop_keep_iterations,
        "live_history_utilization": utilization,
        "triggered_by": "pressure",
    }, ctx.compaction)
    if ctx.correlation_id is not None:
        safe_create_task_fn(record_trace_event_fn(
            correlation_id=ctx.correlation_id,
            session_id=ctx.session_id,
            bot_id=ctx.bot.id,
            client_id=ctx.client_id,
            event_type="context_pruning",
            count=stats["pruned_count"],
            data={
                "scope": "in_loop",
                "chars_saved": stats["chars_saved"],
                "iterations_pruned": stats["iterations_pruned"],
                "tool_call_args_pruned": stats.get("tool_call_args_pruned", 0),
                "tool_call_arg_chars_saved": stats.get("tool_call_arg_chars_saved", 0),
                "iteration": iteration + 1,
                "keep_iterations": in_loop_keep_iterations,
                "live_history_utilization": utilization,
                "triggered_by": "pressure",
            },
        ))


def _emit_context_breakdown_trace(
    *,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    record_trace_event_fn: Any,
    safe_create_task_fn: Any,
    message_prompt_chars_fn: Any | None,
    classify_sys_msg_fn: Any | None,
) -> None:
    if ctx.correlation_id is None or iteration != 0:
        return
    if message_prompt_chars_fn is None:
        from app.agent.prompt_sizing import message_prompt_chars as message_prompt_chars_fn
    if classify_sys_msg_fn is None:
        from app.agent.tracing import _CLASSIFY_SYS_MSG as classify_sys_msg_fn

    breakdown: dict[str, dict] = {}
    for message in state.messages:
        role = message.get("role", "?")
        content = message.get("content") or ""
        chars = message_prompt_chars_fn(message)
        key = role
        if role == "system" and isinstance(content, str):
            key = classify_sys_msg_fn(content)
        if key not in breakdown:
            breakdown[key] = {"count": 0, "chars": 0}
        breakdown[key]["count"] += 1
        breakdown[key]["chars"] += chars

    safe_create_task_fn(record_trace_event_fn(
        correlation_id=ctx.correlation_id,
        session_id=ctx.session_id,
        bot_id=ctx.bot.id,
        client_id=ctx.client_id,
        event_type="context_breakdown",
        data={
            "breakdown": breakdown,
            "total_messages": len(state.messages),
            "total_chars": sum(v["chars"] for v in breakdown.values()),
            "iteration": iteration + 1,
        },
    ))
