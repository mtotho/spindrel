from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.llm import AccumulatedMessage
from app.agent.loop_tool_iteration import LoopToolIterationDone, stream_loop_tool_iteration
from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.loop_cycle_detection import make_signature
from app.config import DEFAULT_SKILL_NUDGE_PROMPT


def _ctx(*, compaction=False):
    return LoopRunContext(
        bot=BotConfig(
            id="bot-1",
            name="Test Bot",
            model="gpt-4",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(),
        ),
        session_id=None,
        client_id="client-1",
        correlation_id=None,
        channel_id=None,
        compaction=compaction,
        native_audio=False,
        user_msg_index=None,
        turn_start=0,
    )


def _settings(**overrides):
    defaults = dict(
        IN_LOOP_PRUNING_ENABLED=False,
        CONTEXT_BUDGET_RESERVE_RATIO=0.15,
        IN_LOOP_PRUNING_PRESSURE_THRESHOLD=0.8,
        CONTEXT_PRUNING_MIN_LENGTH=200,
        SKILL_NUDGE_AFTER_ITERATIONS=0,
        TOOL_LOOP_DETECTION_ENABLED=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _accumulated(*, content=None):
    return AccumulatedMessage(
        content=content,
        tool_calls=[{
            "id": "tc_1",
            "type": "function",
            "function": {"name": "some_tool", "arguments": "{}"},
        }],
    )


async def _noop_dispatch(**kwargs):
    if False:
        yield {}


async def _collect(**overrides):
    state = overrides.pop("state", LoopRunState(messages=[{"role": "user", "content": "hi"}]))
    outputs = [
        item async for item in stream_loop_tool_iteration(
            accumulated_msg=overrides.pop("accumulated_msg", _accumulated()),
            ctx=overrides.pop("ctx", _ctx()),
            state=state,
            iteration=overrides.pop("iteration", 0),
            model=overrides.pop("model", "gpt-4"),
            provider_id=overrides.pop("provider_id", "openai"),
            summarize_settings=overrides.pop("summarize_settings", object()),
            skip_tool_policy=overrides.pop("skip_tool_policy", False),
            effective_allowed=overrides.pop("effective_allowed", None),
            settings_obj=overrides.pop("settings_obj", _settings()),
            session_lock_manager=overrides.pop("session_lock_manager", object()),
            in_loop_keep_iterations=overrides.pop("in_loop_keep_iterations", 2),
            has_manage_bot_skill=overrides.pop("has_manage_bot_skill", False),
            dispatch_iteration_tool_calls_fn=overrides.pop("dispatch_iteration_tool_calls_fn", _noop_dispatch),
            dispatch_tool_call_fn=overrides.pop("dispatch_tool_call_fn", object()),
            is_client_tool_fn=overrides.pop("is_client_tool_fn", object()),
            redact_fn=overrides.pop("redact_fn", lambda text: text),
            prune_in_loop_tool_results_fn=overrides.pop("prune_in_loop_tool_results_fn", lambda *args, **kwargs: {}),
            should_prune_in_loop_fn=overrides.pop("should_prune_in_loop_fn", lambda *args, **kwargs: (False, 0.0)),
            detect_cycle_fn=overrides.pop("detect_cycle_fn", lambda trace: None),
            model_supports_vision_fn=overrides.pop("model_supports_vision_fn", None),
            describe_image_data_fn=overrides.pop("describe_image_data_fn", None),
            get_model_context_window_fn=overrides.pop("get_model_context_window_fn", None),
        )
    ]
    assert not overrides
    return outputs, state


@pytest.mark.asyncio
async def test_dispatch_cancelled_returns_cancelled_done():
    async def _cancel_dispatch(**kwargs):
        yield {"type": "cancelled"}

    outputs, _ = await _collect(dispatch_iteration_tool_calls_fn=_cancel_dispatch)

    assert outputs == [{"type": "cancelled"}, LoopToolIterationDone(cancelled=True)]


@pytest.mark.asyncio
async def test_injected_images_are_added_as_native_vision_parts():
    async def _dispatch_with_image(**kwargs):
        kwargs["state"].iteration_injected_images.append({
            "mime_type": "image/png",
            "base64": "abc123",
        })
        yield {"type": "tool_result", "tool": "some_tool"}

    outputs, state = await _collect(
        dispatch_iteration_tool_calls_fn=_dispatch_with_image,
        model_supports_vision_fn=lambda model: True,
    )

    assert outputs[0] == {"type": "tool_result", "tool": "some_tool"}
    assert isinstance(outputs[-1], LoopToolIterationDone)
    injected = state.messages[-1]
    assert injected["_internal_kind"] == "injected_image_context"
    assert injected["content"][1]["image_url"]["url"] == "data:image/png;base64,abc123"


@pytest.mark.asyncio
async def test_record_plan_progress_result_finishes_turn_without_more_llm_iterations():
    async def _dispatch_progress(**kwargs):
        yield {"type": "tool_result", "tool": "record_plan_progress"}

    outputs, state = await _collect(dispatch_iteration_tool_calls_fn=_dispatch_progress)

    assert outputs == [
        {"type": "tool_result", "tool": "record_plan_progress"},
        {
            "type": "response",
            "text": "Plan progress recorded.",
            "client_actions": [],
        },
        LoopToolIterationDone(finished=True),
    ]
    assert state.messages[-1] == {"role": "assistant", "content": "Plan progress recorded."}


@pytest.mark.asyncio
async def test_record_plan_progress_final_turn_preserves_tool_envelopes():
    plan_envelope = {
        "content_type": "application/vnd.spindrel.plan+json",
        "body": {"title": "Progress"},
        "plain_body": "Progress",
    }

    async def _dispatch_progress(**kwargs):
        state = kwargs["state"]
        state.tool_calls_made.append("record_plan_progress")
        state.tool_envelopes_made.append(plan_envelope)
        yield {"type": "tool_result", "tool": "record_plan_progress"}

    _, state = await _collect(
        accumulated_msg=_accumulated(content="Recording progress."),
        dispatch_iteration_tool_calls_fn=_dispatch_progress,
    )

    assert state.messages[-1]["content"] == "Plan progress recorded."
    assert state.messages[-1]["_tools_used"] == ["record_plan_progress"]
    assert state.messages[-1]["_tool_envelopes"] == [plan_envelope]
    body = state.messages[-1]["_assistant_turn_body"]
    assert body["version"] == 1
    assert "Recording progress." in body["items"][0]["text"]
    assert "Plan progress recorded." in body["items"][0]["text"]


@pytest.mark.asyncio
async def test_injected_images_are_described_for_nonvision_models():
    async def _dispatch_with_image(**kwargs):
        kwargs["state"].iteration_injected_images.append({
            "mime_type": "image/jpeg",
            "base64": "abc123",
        })
        if False:
            yield {}

    describe = AsyncMock(return_value="a dashboard screenshot")

    outputs, state = await _collect(
        dispatch_iteration_tool_calls_fn=_dispatch_with_image,
        model_supports_vision_fn=lambda model: False,
        describe_image_data_fn=describe,
    )

    assert {"type": "llm_retry", "reason": "vision_not_supported", "model": "gpt-4", "attempt": 0, "max_retries": 0, "wait_seconds": 0} in outputs
    assert state.messages[-1]["content"] == "[Image description: a dashboard screenshot]"


@pytest.mark.asyncio
async def test_post_dispatch_pruning_emits_event_and_marks_iteration():
    def _prune(*args, **kwargs):
        return {
            "pruned_count": 1,
            "chars_saved": 200,
            "iterations_pruned": [0],
            "tool_call_args_pruned": 1,
            "tool_call_arg_chars_saved": 50,
        }

    outputs, state = await _collect(
        settings_obj=_settings(IN_LOOP_PRUNING_ENABLED=True),
        should_prune_in_loop_fn=lambda *args, **kwargs: (True, 0.91),
        prune_in_loop_tool_results_fn=_prune,
        get_model_context_window_fn=lambda model, provider_id: 1000,
    )

    event = [item for item in outputs if isinstance(item, dict) and item.get("type") == "context_pruning"][0]
    assert event["live_history_utilization"] == 0.91
    assert event["tool_call_args_pruned"] == 1
    assert state.last_pruned_after_iteration == 0


@pytest.mark.asyncio
async def test_skill_nudge_and_cycle_detection_update_messages_and_break_loop():
    state = LoopRunState(messages=[{"role": "user", "content": "hi"}])
    state.tool_call_trace = [
        make_signature("a", "{}"),
        make_signature("a", "{}"),
        make_signature("a", "{}"),
    ]

    outputs, state = await _collect(
        state=state,
        settings_obj=_settings(SKILL_NUDGE_AFTER_ITERATIONS=1, TOOL_LOOP_DETECTION_ENABLED=True),
        has_manage_bot_skill=True,
        detect_cycle_fn=lambda trace: 1,
    )

    assert state.messages[-1]["content"] == DEFAULT_SKILL_NUDGE_PROMPT
    assert state.loop_broken_reason == "cycle"
    assert state.detected_cycle_len == 1
    assert outputs[-1] == LoopToolIterationDone(break_loop=True)
