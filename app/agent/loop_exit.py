import traceback
from collections.abc import AsyncGenerator
from typing import Any

from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.recording import _record_trace_event
from app.utils import safe_create_task


async def stream_loop_exit_finalization(
    *,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    effective_max_iterations: int,
    tools_param: list[dict[str, Any]] | None,
    model: str,
    effective_provider_id: str | None,
    fallback_models: list[dict] | None,
    llm_call_fn: Any,
    handle_loop_exit_forced_response_fn: Any,
    record_tool_uses_fn: Any | None = None,
    safe_create_task_fn: Any = safe_create_task,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run post-loop finalization and success-path tool-use telemetry."""
    async for event in handle_loop_exit_forced_response_fn(
        ctx=ctx,
        state=state,
        iteration=iteration,
        effective_max_iterations=effective_max_iterations,
        tools_param=tools_param,
        model=model,
        effective_provider_id=effective_provider_id,
        fallback_models=fallback_models,
        llm_call_fn=llm_call_fn,
    ):
        yield event

    if state.terminated:
        return

    if state.tools_to_enroll and ctx.bot.id:
        if record_tool_uses_fn is None:
            from app.services.tool_enrollment import record_use_many as record_tool_uses_fn
        safe_create_task_fn(record_tool_uses_fn(ctx.bot.id, state.tools_to_enroll))


def schedule_loop_error_cleanup(
    *,
    exc: Exception,
    ctx: LoopRunContext,
    state: LoopRunState,
    fire_hook_fn: Any | None = None,
    hook_context_cls: Any | None = None,
    record_trace_event_fn: Any = _record_trace_event,
    safe_create_task_fn: Any = safe_create_task,
    traceback_format_fn: Any = traceback.format_exc,
) -> None:
    """Schedule best-effort hook cleanup and trace persistence after loop errors."""
    try:
        if fire_hook_fn is None or hook_context_cls is None:
            from app.agent.hooks import HookContext, fire_hook

            fire_hook_fn = fire_hook if fire_hook_fn is None else fire_hook_fn
            hook_context_cls = HookContext if hook_context_cls is None else hook_context_cls

        safe_create_task_fn(fire_hook_fn("after_response", hook_context_cls(
            bot_id=ctx.bot.id,
            session_id=ctx.session_id,
            channel_id=ctx.channel_id,
            client_id=ctx.client_id,
            correlation_id=ctx.correlation_id,
            extra={
                "error": True,
                "tool_calls_made": list(state.tool_calls_made),
            },
        )))
    except Exception:
        pass

    if ctx.correlation_id is None:
        return

    safe_create_task_fn(record_trace_event_fn(
        correlation_id=ctx.correlation_id,
        session_id=ctx.session_id,
        bot_id=ctx.bot.id,
        client_id=ctx.client_id,
        event_type="error",
        event_name=type(exc).__name__,
        data={"traceback": traceback_format_fn()[:4000]},
    ))
