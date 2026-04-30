import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agent.llm import AccumulatedMessage
from app.agent.loop_helpers import (
    _append_transcript_text_entry,
    _extract_client_actions,
    _sanitize_llm_text,
)
from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.message_utils import _event_with_compaction_tag, _extract_transcript

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopToolIterationDone:
    cancelled: bool = False
    break_loop: bool = False
    finished: bool = False


async def stream_loop_tool_iteration(
    *,
    accumulated_msg: AccumulatedMessage,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    model: str,
    provider_id: str | None,
    summarize_settings: Any,
    skip_tool_policy: bool,
    effective_allowed: set[str] | None,
    settings_obj: Any,
    session_lock_manager: Any,
    in_loop_keep_iterations: int,
    has_manage_bot_skill: bool,
    dispatch_iteration_tool_calls_fn: Any,
    dispatch_tool_call_fn: Any,
    is_client_tool_fn: Any,
    redact_fn: Any,
    prune_in_loop_tool_results_fn: Any,
    should_prune_in_loop_fn: Any,
    detect_cycle_fn: Any,
    model_supports_vision_fn: Any | None = None,
    describe_image_data_fn: Any | None = None,
    get_model_context_window_fn: Any | None = None,
) -> AsyncGenerator[dict[str, Any] | LoopToolIterationDone, None]:
    """Handle one tool-call iteration after an LLM message requested tools."""
    messages = state.messages
    content = accumulated_msg.content

    if ctx.native_audio and ctx.user_msg_index is not None and not state.transcript_emitted and content:
        transcript, _ = _extract_transcript(content)
        if transcript:
            logger.info("Audio transcript (from tool-call response): %r", transcript[:100])
            yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, ctx.compaction)
            messages[ctx.user_msg_index] = {"role": "user", "content": transcript}
            state.transcript_emitted = True

    intermediate_text = _sanitize_llm_text(content or "")
    intermediate_text = redact_fn(intermediate_text)
    if intermediate_text:
        _append_transcript_text_entry(state.transcript_entries, intermediate_text)
        yield _event_with_compaction_tag(
            {"type": "assistant_text", "text": intermediate_text},
            ctx.compaction,
        )

    tool_calls = accumulated_msg.tool_calls or []
    logger.info("LLM requested %d tool call(s)", len(tool_calls))
    async for dispatch_event in dispatch_iteration_tool_calls_fn(
        accumulated_tool_calls=tool_calls,
        ctx=ctx,
        state=state,
        iteration=iteration,
        provider_id=provider_id,
        summarize_settings=summarize_settings,
        skip_tool_policy=skip_tool_policy,
        effective_allowed=effective_allowed,
        settings_obj=settings_obj,
        session_lock_manager=session_lock_manager,
        dispatch_tool_call_fn=dispatch_tool_call_fn,
        is_client_tool_fn=is_client_tool_fn,
    ):
        yield dispatch_event
        if dispatch_event.get("type") == "cancelled":
            yield LoopToolIterationDone(cancelled=True)
            return
        if _plan_progress_result_ends_turn(dispatch_event):
            text = "Plan progress recorded."
            _append_transcript_text_entry(state.transcript_entries, text)
            state.messages.append(_plan_progress_final_assistant_message(text, state))
            yield _event_with_compaction_tag({
                "type": "response",
                "text": text,
                "client_actions": _extract_client_actions(state.messages, ctx.turn_start) + state.embedded_client_actions,
                **({"correlation_id": str(ctx.correlation_id)} if ctx.correlation_id else {}),
            }, ctx.compaction)
            yield LoopToolIterationDone(finished=True)
            return

    async for image_event in _inject_iteration_images(
        state=state,
        messages=messages,
        model=model,
        compaction=ctx.compaction,
        model_supports_vision_fn=model_supports_vision_fn,
        describe_image_data_fn=describe_image_data_fn,
    ):
        yield image_event

    async for pruning_event in _prune_after_tool_iteration(
        state=state,
        messages=messages,
        iteration=iteration,
        model=model,
        provider_id=provider_id,
        settings_obj=settings_obj,
        in_loop_keep_iterations=in_loop_keep_iterations,
        compaction=ctx.compaction,
        prune_in_loop_tool_results_fn=prune_in_loop_tool_results_fn,
        should_prune_in_loop_fn=should_prune_in_loop_fn,
        get_model_context_window_fn=get_model_context_window_fn,
    ):
        yield pruning_event

    if (
        settings_obj.SKILL_NUDGE_AFTER_ITERATIONS
        and iteration + 1 == settings_obj.SKILL_NUDGE_AFTER_ITERATIONS
        and has_manage_bot_skill
    ):
        from app.config import DEFAULT_SKILL_NUDGE_PROMPT

        messages.append({
            "role": "system",
            "content": DEFAULT_SKILL_NUDGE_PROMPT,
        })

    if settings_obj.TOOL_LOOP_DETECTION_ENABLED and len(state.tool_call_trace) >= 3:
        state.detected_cycle_len = detect_cycle_fn(state.tool_call_trace) or 0
        if state.detected_cycle_len:
            state.loop_broken_reason = "cycle"
            logger.warning(
                "Tool loop detected: cycle length %d after %d calls - breaking",
                state.detected_cycle_len,
                len(state.tool_call_trace),
            )
            yield LoopToolIterationDone(break_loop=True)
            return

    yield LoopToolIterationDone()


def _plan_progress_result_ends_turn(event: dict[str, Any]) -> bool:
    """`record_plan_progress` is an end-of-turn marker, not an invitation to keep executing."""
    return (
        event.get("type") == "tool_result"
        and event.get("tool") == "record_plan_progress"
        and not event.get("error")
    )


def _plan_progress_final_assistant_message(text: str, state: LoopRunState) -> dict[str, Any]:
    """Build the synthetic final assistant turn for progress-marker tool turns."""
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if state.tool_calls_made:
        message["_tools_used"] = list(state.tool_calls_made)
        if state.tool_envelopes_made:
            message["_tool_envelopes"] = list(state.tool_envelopes_made)
    if state.thinking_content:
        message["_thinking_content"] = state.thinking_content
    if state.tool_calls_made and state.transcript_entries:
        message["_assistant_turn_body"] = {
            "version": 1,
            "items": list(state.transcript_entries),
        }
    return message


async def _inject_iteration_images(
    *,
    state: LoopRunState,
    messages: list[dict],
    model: str,
    compaction: bool,
    model_supports_vision_fn: Any | None,
    describe_image_data_fn: Any | None,
) -> AsyncGenerator[dict[str, Any], None]:
    images = list(state.iteration_injected_images)
    if not images:
        return

    if model_supports_vision_fn is None:
        from app.services.providers import model_supports_vision as model_supports_vision_fn

    if model_supports_vision_fn(model):
        image_parts: list[dict] = [{"type": "text", "text": "[Requested image(s) for your analysis]"}]
        for img in images:
            mime = img.get("mime_type", "image/jpeg")
            b64 = img.get("base64", "")
            if b64:
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
        if len(image_parts) > 1:
            messages.append({
                "role": "user",
                "content": image_parts,
                "_hidden": True,
                "_suppress_outbox": True,
                "_internal_kind": "injected_image_context",
            })
        return

    if describe_image_data_fn is None:
        from app.agent.llm import _describe_image_data as describe_image_data_fn

    desc_parts: list[str] = []
    for img in images:
        mime = img.get("mime_type", "image/jpeg")
        b64 = img.get("base64", "")
        if not b64:
            continue
        data_url = f"data:{mime};base64,{b64}"
        desc = await describe_image_data_fn(data_url)
        desc_parts.append(
            f"[Image description: {desc}]" if desc
            else "[An image was attached but could not be described.]"
        )
    if desc_parts:
        messages.append({
            "role": "user",
            "content": "\n\n".join(desc_parts),
            "_hidden": True,
            "_suppress_outbox": True,
            "_internal_kind": "injected_image_context",
        })
        yield _event_with_compaction_tag({
            "type": "llm_retry",
            "reason": "vision_not_supported",
            "model": model,
            "attempt": 0,
            "max_retries": 0,
            "wait_seconds": 0,
        }, compaction)


async def _prune_after_tool_iteration(
    *,
    state: LoopRunState,
    messages: list[dict],
    iteration: int,
    model: str,
    provider_id: str | None,
    settings_obj: Any,
    in_loop_keep_iterations: int,
    compaction: bool,
    prune_in_loop_tool_results_fn: Any,
    should_prune_in_loop_fn: Any,
    get_model_context_window_fn: Any | None,
) -> AsyncGenerator[dict[str, Any], None]:
    if not settings_obj.IN_LOOP_PRUNING_ENABLED or state.last_pruned_after_iteration == iteration:
        return

    available_budget_tokens = 0
    try:
        if get_model_context_window_fn is None:
            from app.agent.context_budget import get_model_context_window as get_model_context_window_fn
        window = get_model_context_window_fn(model, provider_id)
        if window > 0:
            available_budget_tokens = max(
                0,
                window - int(window * settings_obj.CONTEXT_BUDGET_RESERVE_RATIO),
            )
    except Exception:
        available_budget_tokens = 0

    should_prune, utilization = should_prune_in_loop_fn(
        messages,
        available_budget_tokens=available_budget_tokens,
        pressure_threshold=settings_obj.IN_LOOP_PRUNING_PRESSURE_THRESHOLD,
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

    state.last_pruned_after_iteration = iteration
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
    }, compaction)
