from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.agent.loop_dispatch import dispatch_iteration_tool_calls
from app.agent.loop_state import LoopRunContext, LoopRunState
from app.agent.tool_dispatch import ToolCallResult


def _ctx() -> LoopRunContext:
    return LoopRunContext(
        bot=BotConfig(
            id="bot-1",
            name="Test Bot",
            model="gpt-4",
            system_prompt="System.",
            memory=MemoryConfig(),
        ),
        session_id=None,
        client_id="client-1",
        correlation_id=None,
        channel_id=None,
        compaction=False,
        native_audio=False,
        user_msg_index=None,
        turn_start=0,
    )


def _tc(name: str, args: str, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        PARALLEL_TOOL_EXECUTION=True,
        PARALLEL_TOOL_MAX_CONCURRENT=5,
        TOOL_TURN_AGGREGATE_CAP_CHARS=0,
    )


def _summarize_settings() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=False,
        threshold=0,
        model="",
        max_tokens=0,
        exclude=frozenset(),
    )


@pytest.mark.asyncio
async def test_generic_readonly_tool_results_are_cached_with_registry_tier():
    calls = 0

    async def _dispatch(**kwargs):
        nonlocal calls
        calls += 1
        return ToolCallResult(
            result_for_llm='{"ok": true}',
            tool_event={"type": "tool_result", "tool": kwargs["name"], "result": '{"ok": true}'},
        )

    state = LoopRunState(messages=[{"role": "user", "content": "hi"}])
    tool_calls = [
        _tc("custom_readonly", '{"q":"x"}', "tc_1"),
        _tc("custom_readonly", '{"q":"x"}', "tc_2"),
    ]

    with patch("app.agent.loop_dispatch.get_tool_safety_tier", return_value="readonly"):
        events = [
            event async for event in dispatch_iteration_tool_calls(
                accumulated_tool_calls=tool_calls,
                ctx=_ctx(),
                state=state,
                iteration=0,
                provider_id="openai",
                summarize_settings=_summarize_settings(),
                skip_tool_policy=False,
                effective_allowed=None,
                settings_obj=_settings(),
                session_lock_manager=SimpleNamespace(is_cancel_requested=lambda session_id: False),
                dispatch_tool_call_fn=_dispatch,
                is_client_tool_fn=lambda name: False,
            )
        ]

    assert calls == 1
    assert any(event.get("cache_hit") is True for event in events)
    assert state.messages[-1]["_cache_hit"] is True


@pytest.mark.asyncio
async def test_duplicate_mutating_tool_block_emits_dedicated_event():
    dispatch = AsyncMock(return_value=ToolCallResult(
        result_for_llm='{"ok": true}',
        tool_event={"type": "tool_result", "tool": "mutate", "result": '{"ok": true}'},
    ))
    state = LoopRunState(messages=[{"role": "user", "content": "hi"}])
    tool_calls = [
        _tc("mutate", '{"id":1}', "tc_1"),
        _tc("mutate", '{"id":1}', "tc_2"),
    ]

    with patch("app.agent.loop_dispatch.get_tool_safety_tier", return_value="mutating"):
        events = [
            event async for event in dispatch_iteration_tool_calls(
                accumulated_tool_calls=tool_calls,
                ctx=_ctx(),
                state=state,
                iteration=0,
                provider_id="openai",
                summarize_settings=_summarize_settings(),
                skip_tool_policy=False,
                effective_allowed=None,
                settings_obj=_settings(),
                session_lock_manager=SimpleNamespace(is_cancel_requested=lambda session_id: False),
                dispatch_tool_call_fn=dispatch,
                is_client_tool_fn=lambda name: False,
            )
        ]

    assert dispatch.await_count == 1
    assert any(event.get("type") == "tool_duplicate_blocked" for event in events)
