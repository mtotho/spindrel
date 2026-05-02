import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.llm import AccumulatedMessage, FallbackInfo
from app.agent.loop_llm import LoopLlmIterationDone, stream_loop_llm_iteration
from app.agent.loop_state import LoopRunContext, LoopRunState


def _make_ctx(*, correlation_id=None, session_id=None, compaction=False):
    bot = BotConfig(
        id="bot-1",
        name="Test Bot",
        model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(),
    )
    return LoopRunContext(
        bot=bot,
        session_id=session_id,
        client_id="client-1",
        correlation_id=correlation_id,
        channel_id=uuid.uuid4(),
        compaction=compaction,
        native_audio=False,
        user_msg_index=None,
        turn_start=0,
    )


def _usage(*, prompt=100, completion=20):
    usage = MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = prompt + completion
    return usage


def _streaming_fn(*items):
    async def _stream(*args, **kwargs):
        for item in items:
            yield item

    return _stream


def _close_task(coro):
    if hasattr(coro, "close"):
        coro.close()


async def _collect(**overrides):
    ctx = overrides.pop("ctx", _make_ctx())
    state = overrides.pop("state", LoopRunState(messages=[{"role": "user", "content": "hi"}]))
    session_lock_manager = overrides.pop("session_lock_manager", MagicMock(is_cancel_requested=MagicMock(return_value=False)))
    fire_hook_fn = overrides.pop("fire_hook_fn", AsyncMock())
    record_trace_event_fn = overrides.pop("record_trace_event_fn", AsyncMock())
    record_fallback_event_fn = overrides.pop("record_fallback_event_fn", AsyncMock())
    last_fallback_info_get_fn = overrides.pop("last_fallback_info_get_fn", lambda: None)
    outputs = [
        item async for item in stream_loop_llm_iteration(
            ctx=ctx,
            state=state,
            iteration=overrides.pop("iteration", 2),
            model=overrides.pop("model", "gpt-4"),
            tools_param=overrides.pop("tools_param", None),
            tool_choice=overrides.pop("tool_choice", None),
            effective_provider_id=overrides.pop("effective_provider_id", "openai"),
            model_params=overrides.pop("model_params", {"temperature": 0.2}),
            fallback_models=overrides.pop("fallback_models", None),
            session_lock_manager=session_lock_manager,
            llm_call_stream_fn=overrides.pop("llm_call_stream_fn"),
            last_fallback_info_get_fn=last_fallback_info_get_fn,
            fire_hook_fn=fire_hook_fn,
            record_trace_event_fn=record_trace_event_fn,
            record_fallback_event_fn=record_fallback_event_fn,
            safe_create_task_fn=_close_task,
            monotonic_fn=overrides.pop("monotonic_fn", MagicMock(side_effect=[10.0, 10.25])),
        )
    ]
    assert not overrides
    return outputs, state, fire_hook_fn, record_trace_event_fn, record_fallback_event_fn


@pytest.mark.asyncio
async def test_stream_events_are_yielded_and_traced_with_iteration_metadata():
    ctx = _make_ctx(correlation_id=uuid.uuid4(), compaction=True)
    acc = AccumulatedMessage(content="done", usage=_usage())

    outputs, _, _, record_trace, _ = await _collect(
        ctx=ctx,
        llm_call_stream_fn=_streaming_fn({"type": "llm_retry", "wait_seconds": 1}, acc),
    )

    assert outputs[0] == {"type": "llm_retry", "wait_seconds": 1, "compaction": True}
    assert isinstance(outputs[-1], LoopLlmIterationDone)
    assert record_trace.call_args_list[0].kwargs["event_type"] == "llm_retry"
    assert record_trace.call_args_list[0].kwargs["data"]["iteration"] == 3


@pytest.mark.asyncio
async def test_inline_image_routing_trace_records_direct_vision_path():
    ctx = _make_ctx(correlation_id=uuid.uuid4())
    state = LoopRunState(messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "see attached"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ],
    }])
    acc = AccumulatedMessage(content="done", usage=_usage())

    with patch("app.services.providers.model_supports_vision", return_value=True):
        _, _, _, record_trace, _ = await _collect(
            ctx=ctx,
            state=state,
            iteration=0,
            model="gpt-5.4",
            effective_provider_id="chatgpt-subscription",
            llm_call_stream_fn=_streaming_fn(acc),
        )

    routing_call = next(
        call for call in record_trace.call_args_list
        if call.kwargs["event_type"] == "attachment_vision_routing"
    )
    assert routing_call.kwargs["data"] == {
        "source_image_count": 1,
        "inline_image_count": 1,
        "stripped_image_count": 0,
        "model_supports_vision": True,
        "model": "gpt-5.4",
        "provider_id": "chatgpt-subscription",
        "fallback_reason": None,
        "iteration": 1,
    }


@pytest.mark.asyncio
async def test_inline_image_routing_trace_records_no_vision_strip_path():
    ctx = _make_ctx(correlation_id=uuid.uuid4())
    state = LoopRunState(messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "see attached"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,def"}},
        ],
    }])
    acc = AccumulatedMessage(content="done", usage=_usage())

    with patch("app.services.providers.model_supports_vision", return_value=False):
        _, _, _, record_trace, _ = await _collect(
            ctx=ctx,
            state=state,
            iteration=0,
            model="gpt-5.4",
            effective_provider_id="chatgpt-subscription",
            llm_call_stream_fn=_streaming_fn(acc),
        )

    routing_call = next(
        call for call in record_trace.call_args_list
        if call.kwargs["event_type"] == "attachment_vision_routing"
    )
    data = routing_call.kwargs["data"]
    assert data["source_image_count"] == 2
    assert data["inline_image_count"] == 0
    assert data["stripped_image_count"] == 2
    assert data["model_supports_vision"] is False
    assert data["fallback_reason"] == "model_supports_vision_false"


@pytest.mark.asyncio
async def test_cancellation_during_stream_yields_cancelled_without_done_result():
    session_id = uuid.uuid4()
    ctx = _make_ctx(session_id=session_id)
    session_lock_manager = MagicMock(is_cancel_requested=MagicMock(return_value=True))

    outputs, _, fire_hook, _, _ = await _collect(
        ctx=ctx,
        session_lock_manager=session_lock_manager,
        llm_call_stream_fn=_streaming_fn({"type": "llm_retry"}),
    )

    assert outputs == [{"type": "llm_retry"}, {"type": "cancelled"}]
    assert fire_hook.call_args_list[0].args[0] == "before_llm_call"
    assert len(fire_hook.call_args_list) == 1


@pytest.mark.asyncio
async def test_usage_accounting_subtracts_cached_tokens_and_records_trace():
    ctx = _make_ctx(correlation_id=uuid.uuid4())
    acc = AccumulatedMessage(
        content="done",
        usage=_usage(prompt=100, completion=25),
        cached_tokens=30,
        response_cost=0.25,
    )

    outputs, state, _, record_trace, _ = await _collect(
        ctx=ctx,
        llm_call_stream_fn=_streaming_fn(acc),
    )

    assert isinstance(outputs[-1], LoopLlmIterationDone)
    assert state.current_prompt_tokens_total == 70
    usage_call = [c for c in record_trace.call_args_list if c.kwargs["event_type"] == "token_usage"][0]
    assert usage_call.kwargs["duration_ms"] == 250
    assert usage_call.kwargs["data"]["current_prompt_tokens"] == 70
    assert usage_call.kwargs["data"]["cached_prompt_tokens"] == 30
    assert usage_call.kwargs["data"]["response_cost"] == 0.25


@pytest.mark.asyncio
async def test_fallback_info_emits_event_and_records_telemetry():
    ctx = _make_ctx(correlation_id=uuid.uuid4())
    acc = AccumulatedMessage(content="done", usage=_usage())
    fallback_info = FallbackInfo(
        original_model="primary",
        fallback_model="backup",
        reason="RateLimitError",
        original_error="rate limited",
    )

    outputs, _, fire_hook, record_trace, record_fallback = await _collect(
        ctx=ctx,
        llm_call_stream_fn=_streaming_fn(acc),
        last_fallback_info_get_fn=lambda: fallback_info,
    )

    fallback_event = [item for item in outputs if isinstance(item, dict) and item.get("type") == "fallback"][0]
    assert fallback_event["original_model"] == "primary"
    assert fallback_event["fallback_model"] == "backup"
    assert fire_hook.call_args_list[1].args[1].extra["fallback_used"] is True
    assert any(c.kwargs["event_type"] == "model_fallback" for c in record_trace.call_args_list)
    assert record_fallback.call_args.args[0] is fallback_info


@pytest.mark.asyncio
async def test_thinking_content_is_yielded_and_accumulated():
    acc = AccumulatedMessage(content="done", usage=_usage(), thinking_content="hidden reasoning")

    outputs, state, _, _, _ = await _collect(
        llm_call_stream_fn=_streaming_fn(acc),
    )

    assert {"type": "thinking_content", "text": "hidden reasoning"} in outputs
    assert state.thinking_content == "hidden reasoning"
    assert isinstance(outputs[-1], LoopLlmIterationDone)
