import logging
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any

from app.agent.hooks import HookContext
from app.agent.llm import AccumulatedMessage
from app.agent.loop_helpers import _record_fallback_event, _sanitize_messages
from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.message_utils import _event_with_compaction_tag
from app.agent.recording import _record_trace_event
from app.utils import safe_create_task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopLlmIterationDone:
    accumulated_msg: AccumulatedMessage
    effective_model: str
    latency_ms: int


async def stream_loop_llm_iteration(
    *,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    model: str,
    tools_param: list[dict[str, Any]] | None,
    tool_choice: Any,
    effective_provider_id: str | None,
    model_params: dict[str, Any] | None,
    fallback_models: list[dict] | None,
    session_lock_manager: Any,
    llm_call_stream_fn: Any,
    last_fallback_info_get_fn: Callable[[], Any],
    fire_hook_fn: Any,
    record_trace_event_fn: Any = _record_trace_event,
    record_fallback_event_fn: Any = _record_fallback_event,
    safe_create_task_fn: Any = safe_create_task,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> AsyncGenerator[dict[str, Any] | LoopLlmIterationDone, None]:
    """Run one provider-streaming LLM iteration and emit loop events.

    The caller keeps orchestration ownership; this stage owns provider-stream
    details, lifecycle hooks, fallback telemetry, token usage, and thinking
    accumulation for the iteration.
    """
    bot = ctx.bot
    effective_model = model
    state.messages = _sanitize_messages(state.messages)
    messages = state.messages

    llm_started_at = monotonic_fn()

    safe_create_task_fn(fire_hook_fn("before_llm_call", HookContext(
        bot_id=bot.id,
        session_id=ctx.session_id,
        channel_id=ctx.channel_id,
        client_id=ctx.client_id,
        correlation_id=ctx.correlation_id,
        extra={
            "model": effective_model,
            "message_count": len(messages),
            "tools_count": len(tools_param) if tools_param else 0,
            "provider_id": effective_provider_id,
            "iteration": iteration + 1,
        },
    )))

    accumulated_msg: AccumulatedMessage | None = None
    async for item in llm_call_stream_fn(
        effective_model,
        messages,
        tools_param,
        tool_choice,
        provider_id=effective_provider_id,
        model_params=model_params,
        fallback_models=fallback_models,
    ):
        if isinstance(item, AccumulatedMessage):
            accumulated_msg = item
        else:
            if isinstance(item, dict) and ctx.correlation_id is not None:
                event_type = item.get("type")
                if event_type in ("llm_retry", "llm_fallback", "llm_cooldown_skip", "llm_error"):
                    safe_create_task_fn(record_trace_event_fn(
                        correlation_id=ctx.correlation_id,
                        session_id=ctx.session_id,
                        bot_id=bot.id,
                        client_id=ctx.client_id,
                        event_type=event_type,
                        data={
                            **{k: v for k, v in item.items() if k != "type"},
                            "iteration": iteration + 1,
                        },
                    ))
            yield _event_with_compaction_tag(item, ctx.compaction)

        if ctx.session_id and session_lock_manager.is_cancel_requested(ctx.session_id):
            logger.info("Cancellation requested for session %s (during LLM stream)", ctx.session_id)
            yield _event_with_compaction_tag({"type": "cancelled"}, ctx.compaction)
            return

    latency_ms = int((monotonic_fn() - llm_started_at) * 1000)
    if accumulated_msg is None:
        raise RuntimeError("LLM stream completed without yielding an AccumulatedMessage")

    fallback_info = last_fallback_info_get_fn()
    after_llm_extra: dict[str, Any] = {
        "model": effective_model,
        "duration_ms": latency_ms,
        "prompt_tokens": accumulated_msg.usage.prompt_tokens if accumulated_msg.usage else None,
        "completion_tokens": accumulated_msg.usage.completion_tokens if accumulated_msg.usage else None,
        "total_tokens": accumulated_msg.usage.total_tokens if accumulated_msg.usage else None,
        "tool_calls_count": len(accumulated_msg.tool_calls) if accumulated_msg.tool_calls else 0,
        "fallback_used": fallback_info is not None,
        "fallback_model": fallback_info.fallback_model if fallback_info else None,
        "iteration": iteration + 1,
        "provider_id": effective_provider_id,
    }
    safe_create_task_fn(fire_hook_fn("after_llm_call", HookContext(
        bot_id=bot.id,
        session_id=ctx.session_id,
        channel_id=ctx.channel_id,
        client_id=ctx.client_id,
        correlation_id=ctx.correlation_id,
        extra=after_llm_extra,
    )))

    if fallback_info is not None:
        logger.warning(
            "Fallback used: %s -> %s (reason: %s)",
            fallback_info.original_model,
            fallback_info.fallback_model,
            fallback_info.reason,
        )
        yield _event_with_compaction_tag({
            "type": "fallback",
            "original_model": fallback_info.original_model,
            "fallback_model": fallback_info.fallback_model,
            "reason": fallback_info.reason,
        }, ctx.compaction)
        if ctx.correlation_id is not None:
            safe_create_task_fn(record_trace_event_fn(
                correlation_id=ctx.correlation_id,
                session_id=ctx.session_id,
                bot_id=bot.id,
                client_id=ctx.client_id,
                event_type="model_fallback",
                data={
                    "original_model": fallback_info.original_model,
                    "fallback_model": fallback_info.fallback_model,
                    "reason": fallback_info.reason,
                    "original_error": fallback_info.original_error,
                    "iteration": iteration + 1,
                },
                duration_ms=latency_ms,
            ))
        safe_create_task_fn(record_fallback_event_fn(
            fallback_info,
            session_id=ctx.session_id,
            channel_id=ctx.channel_id,
            bot_id=bot.id,
        ))

    messages.append(accumulated_msg.to_msg_dict())

    if accumulated_msg.usage:
        logger.debug(
            "Token usage: prompt=%d completion=%d total=%d",
            accumulated_msg.usage.prompt_tokens,
            accumulated_msg.usage.completion_tokens,
            accumulated_msg.usage.total_tokens,
        )
        gross_prompt_tokens = accumulated_msg.usage.prompt_tokens
        cached_prompt_tokens = accumulated_msg.cached_tokens
        current_prompt_tokens = gross_prompt_tokens
        if cached_prompt_tokens is not None:
            current_prompt_tokens = max(0, gross_prompt_tokens - cached_prompt_tokens)
        state.current_prompt_tokens_total += int(current_prompt_tokens or 0)
        if ctx.correlation_id is not None:
            usage_data = {
                "prompt_tokens": gross_prompt_tokens,
                "gross_prompt_tokens": gross_prompt_tokens,
                "current_prompt_tokens": current_prompt_tokens,
                "completion_tokens": accumulated_msg.usage.completion_tokens,
                "total_tokens": accumulated_msg.usage.total_tokens,
                "consumed_tokens": gross_prompt_tokens,
                "iteration": iteration + 1,
                "model": effective_model,
                "provider_id": effective_provider_id,
                "channel_id": str(ctx.channel_id) if ctx.channel_id else None,
            }
            if cached_prompt_tokens is not None:
                usage_data["cached_tokens"] = cached_prompt_tokens
                usage_data["cached_prompt_tokens"] = cached_prompt_tokens
            if accumulated_msg.response_cost is not None:
                usage_data["response_cost"] = accumulated_msg.response_cost
            safe_create_task_fn(record_trace_event_fn(
                correlation_id=ctx.correlation_id,
                session_id=ctx.session_id,
                bot_id=bot.id,
                client_id=ctx.client_id,
                event_type="token_usage",
                data=usage_data,
                duration_ms=latency_ms,
            ))

    if accumulated_msg.thinking_content:
        state.append_thinking(accumulated_msg.thinking_content)
        yield _event_with_compaction_tag(
            {"type": "thinking_content", "text": accumulated_msg.thinking_content},
            ctx.compaction,
        )

    yield LoopLlmIterationDone(
        accumulated_msg=accumulated_msg,
        effective_model=effective_model,
        latency_ms=latency_ms,
    )
