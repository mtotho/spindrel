from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agent.llm import AccumulatedMessage
from app.agent.loop_state import LoopRunContext, LoopRunState


@dataclass(frozen=True)
class LoopRecoveryDone:
    has_tool_calls: bool
    return_loop: bool = False


async def stream_loop_recovery(
    *,
    accumulated_msg: AccumulatedMessage,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    model: str,
    tools_param: list[dict[str, Any]] | None,
    effective_provider_id: str | None,
    fallback_models: list[dict] | None,
    effective_allowed: set[str] | None,
    recover_tool_calls_from_text_fn: Any,
    handle_no_tool_calls_path_fn: Any,
    llm_call_fn: Any,
) -> AsyncGenerator[dict[str, Any] | LoopRecoveryDone, None]:
    """Recover text-encoded tool calls or run the terminal no-tool branch."""
    recover_tool_calls_from_text_fn(
        accumulated_msg,
        state.messages,
        effective_allowed,
    )

    if accumulated_msg.tool_calls:
        yield LoopRecoveryDone(has_tool_calls=True)
        return

    async for event in handle_no_tool_calls_path_fn(
        accumulated_msg=accumulated_msg,
        ctx=ctx,
        state=state,
        iteration=iteration,
        model=model,
        tools_param=tools_param,
        effective_provider_id=effective_provider_id,
        fallback_models=fallback_models,
        llm_call_fn=llm_call_fn,
    ):
        yield event
    yield LoopRecoveryDone(has_tool_calls=False, return_loop=True)
