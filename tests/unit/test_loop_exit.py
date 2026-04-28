from uuid import uuid4

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.loop_exit import schedule_loop_error_cleanup, stream_loop_exit_finalization
from app.agent.loop_state import LoopRunContext, LoopRunState


def _ctx(*, bot_id="bot-1", correlation_id=None):
    return LoopRunContext(
        bot=BotConfig(
            id=bot_id,
            name="Test Bot",
            model="gpt-4",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(),
        ),
        session_id=None,
        client_id="client-1",
        correlation_id=correlation_id,
        channel_id=None,
        compaction=False,
        native_audio=False,
        user_msg_index=None,
        turn_start=0,
    )


@pytest.mark.asyncio
async def test_exit_finalization_delegates_forced_response_and_records_tool_uses():
    calls = []

    async def _forced_response(**kwargs):
        calls.append(kwargs)
        yield {"type": "warning", "code": "max_iterations"}
        yield {"type": "response", "text": "done"}

    scheduled = []

    def _record_tool_uses(bot_id, tools):
        return {"bot_id": bot_id, "tools": list(tools)}

    state = LoopRunState(messages=[{"role": "user", "content": "hi"}])
    state.tools_to_enroll.extend(["search", "calculator"])

    outputs = [
        event async for event in stream_loop_exit_finalization(
            ctx=_ctx(),
            state=state,
            iteration=2,
            effective_max_iterations=3,
            tools_param=[{"function": {"name": "search"}}],
            model="gpt-4",
            effective_provider_id="openai",
            fallback_models=[{"model": "gpt-4o-mini"}],
            llm_call_fn=object(),
            handle_loop_exit_forced_response_fn=_forced_response,
            record_tool_uses_fn=_record_tool_uses,
            safe_create_task_fn=scheduled.append,
        )
    ]

    assert outputs == [
        {"type": "warning", "code": "max_iterations"},
        {"type": "response", "text": "done"},
    ]
    assert calls[0]["iteration"] == 2
    assert calls[0]["effective_max_iterations"] == 3
    assert scheduled == [{"bot_id": "bot-1", "tools": ["search", "calculator"]}]


@pytest.mark.asyncio
async def test_exit_finalization_skips_tool_use_recording_when_forced_response_terminates():
    async def _forced_response(**kwargs):
        kwargs["state"].terminated = True
        yield {"type": "error", "code": "llm_error"}

    state = LoopRunState(messages=[])
    state.tools_to_enroll.append("search")
    scheduled = []

    outputs = [
        event async for event in stream_loop_exit_finalization(
            ctx=_ctx(),
            state=state,
            iteration=0,
            effective_max_iterations=1,
            tools_param=None,
            model="gpt-4",
            effective_provider_id="openai",
            fallback_models=None,
            llm_call_fn=object(),
            handle_loop_exit_forced_response_fn=_forced_response,
            record_tool_uses_fn=lambda bot_id, tools: object(),
            safe_create_task_fn=scheduled.append,
        )
    ]

    assert outputs == [{"type": "error", "code": "llm_error"}]
    assert scheduled == []


def test_error_cleanup_schedules_hook_and_trace():
    class CapturingHookContext:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    hook_calls = []
    trace_calls = []
    scheduled = []
    corr = uuid4()
    state = LoopRunState(messages=[])
    state.tool_calls_made.extend(["search"])

    def _fire_hook(name, ctx):
        hook_calls.append((name, ctx))
        return "hook-task"

    def _record_trace_event(**kwargs):
        trace_calls.append(kwargs)
        return "trace-task"

    exc = RuntimeError("boom")
    schedule_loop_error_cleanup(
        exc=exc,
        ctx=_ctx(correlation_id=corr),
        state=state,
        fire_hook_fn=_fire_hook,
        hook_context_cls=CapturingHookContext,
        record_trace_event_fn=_record_trace_event,
        safe_create_task_fn=scheduled.append,
        traceback_format_fn=lambda: "traceback text",
    )

    assert scheduled == ["hook-task", "trace-task"]
    assert hook_calls[0][0] == "after_response"
    assert hook_calls[0][1].kwargs["extra"] == {
        "error": True,
        "tool_calls_made": ["search"],
    }
    assert trace_calls[0]["correlation_id"] == corr
    assert trace_calls[0]["event_type"] == "error"
    assert trace_calls[0]["event_name"] == "RuntimeError"
    assert trace_calls[0]["data"] == {"traceback": "traceback text"}
