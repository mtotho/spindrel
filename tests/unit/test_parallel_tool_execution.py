"""Tests for parallel tool execution in the agent loop."""
import asyncio
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig


@pytest.fixture(autouse=True)
async def _cleanup_dangling_tasks():
    """Cancel dangling fire-and-forget tasks after each test to prevent inter-test leaks."""
    yield
    # Give pending tasks a moment to settle, then cancel stragglers
    await asyncio.sleep(0)
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
from app.agent.llm import AccumulatedMessage
from app.agent.tool_dispatch import ToolCallResult


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _mock_tool_call(name="test_tool", args='{}', tc_id="tc_1"):
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args
    return tc


def _mock_accumulated(content="Hello", tool_calls=None, completion_tokens=50):
    tc_list = None
    if tool_calls:
        tc_list = [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ]
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = completion_tokens
    usage.total_tokens = 100 + completion_tokens
    return AccumulatedMessage(
        content=content,
        tool_calls=tc_list,
        usage=usage,
    )


def _mock_response(content="Hello", tool_calls=None):
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls or []
    choice.finish_reason = "stop" if not tool_calls else "tool_calls"
    dump = {"role": "assistant", "content": content}
    if tool_calls:
        dump["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ]
    choice.message.model_dump = MagicMock(return_value=dump)
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    resp.usage.total_tokens = 150
    return resp


def _make_stream_side_effects(*accumulated_messages):
    _msgs = list(accumulated_messages)
    _idx = {"n": 0}

    async def _stream(*args, **kwargs):
        idx = _idx["n"]
        _idx["n"] += 1
        msg = _msgs[idx] if idx < len(_msgs) else _msgs[-1]
        yield msg

    return _stream


def _default_mock_settings(**overrides):
    s = MagicMock()
    defaults = dict(
        AGENT_MAX_ITERATIONS=15,
        AGENT_TRACE=False,
        TOOL_LOOP_DETECTION_ENABLED=False,
        TOOL_RESULT_SUMMARIZE_ENABLED=False,
        TOOL_RESULT_SUMMARIZE_THRESHOLD=99999,
        TOOL_RESULT_SUMMARIZE_MODEL="",
        TOOL_RESULT_SUMMARIZE_MAX_TOKENS=500,
        TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS=[],
        PARALLEL_TOOL_EXECUTION=True,
        PARALLEL_TOOL_MAX_CONCURRENT=10,
        IN_LOOP_PRUNING_ENABLED=False,
        IN_LOOP_PRUNING_KEEP_ITERATIONS=1,
        CONTEXT_PRUNING_MIN_LENGTH=200,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# Standard patches for running run_agent_tool_loop with tool dispatch mocked
_COMMON_PATCHES = [
    "app.agent.loop.get_local_tool_schemas",
    "app.agent.loop.get_client_tool_schemas",
]


class TestParallelToolExecution:
    """Tests for the parallel tool dispatch path."""

    @pytest.mark.asyncio
    async def test_multiple_tools_dispatch_concurrently(self):
        """Two tools should be dispatched concurrently when PARALLEL_TOOL_EXECUTION=True."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        tc2 = _mock_tool_call("tool_b", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()

        dispatch_times = []

        async def _track_dispatch(**kwargs):
            dispatch_times.append(time.monotonic())
            await asyncio.sleep(0.05)  # simulate async I/O
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_track_dispatch), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "use both tools"}], bot
            ):
                events.append(event)

        # Both dispatches should start nearly simultaneously (within 20ms of each other)
        assert len(dispatch_times) == 2
        assert abs(dispatch_times[1] - dispatch_times[0]) < 0.02

        # Verify tool_start events emitted for both tools
        tool_starts = [e for e in events if e["type"] == "tool_start"]
        assert len(tool_starts) == 2
        assert tool_starts[0]["tool"] == "tool_a"
        assert tool_starts[1]["tool"] == "tool_b"

        # Verify tool results are in order
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 2
        assert tool_results[0]["tool"] == "tool_a"
        assert tool_results[1]["tool"] == "tool_b"

    @pytest.mark.asyncio
    async def test_single_tool_uses_sequential_path(self):
        """With only 1 tool call, the sequential path should be used even when parallel is enabled."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()
        dispatch_mock = AsyncMock(return_value=ToolCallResult(
            result="ok",
            result_for_llm='{"ok": true}',
            tool_event={"type": "tool_result", "tool": "tool_a", "result": "ok"},
        ))

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", dispatch_mock), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "use one tool"}], bot
            ):
                events.append(event)

        # Single tool = sequential path: tool_start appears before tool_result
        tool_events = [e for e in events if e["type"] in ("tool_start", "tool_result")]
        assert tool_events[0]["type"] == "tool_start"
        assert tool_events[1]["type"] == "tool_result"
        dispatch_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_setting_uses_sequential_path(self):
        """With PARALLEL_TOOL_EXECUTION=False, multiple tools dispatch sequentially."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        tc2 = _mock_tool_call("tool_b", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()

        dispatch_times = []

        async def _track_dispatch(**kwargs):
            dispatch_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_track_dispatch), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings(PARALLEL_TOOL_EXECUTION=False)):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "use both tools"}], bot
            ):
                events.append(event)

        # Sequential: second dispatch starts after first completes (~50ms gap)
        assert len(dispatch_times) == 2
        assert dispatch_times[1] - dispatch_times[0] >= 0.04

        # Sequential path interleaves start/result events
        tool_events = [e for e in events if e["type"] in ("tool_start", "tool_result")]
        assert [e["type"] for e in tool_events] == ["tool_start", "tool_result", "tool_start", "tool_result"]

    @pytest.mark.asyncio
    async def test_message_ordering_preserved(self):
        """Tool results should be added to messages in the original order."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("slow_tool", '{}', "tc_1")
        tc2 = _mock_tool_call("fast_tool", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()
        messages = [{"role": "user", "content": "test ordering"}]

        async def _variable_dispatch(**kwargs):
            if kwargs["name"] == "slow_tool":
                await asyncio.sleep(0.1)  # slow
                return ToolCallResult(
                    result="slow_result",
                    result_for_llm='{"result": "slow"}',
                    tool_event={"type": "tool_result", "tool": "slow_tool", "result": "slow_result"},
                )
            else:
                return ToolCallResult(
                    result="fast_result",
                    result_for_llm='{"result": "fast"}',
                    tool_event={"type": "tool_result", "tool": "fast_tool", "result": "fast_result"},
                )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_variable_dispatch), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()):
            events = []
            async for event in run_agent_tool_loop(messages, bot):
                events.append(event)

        # Results should be in original order (slow first, fast second) despite fast finishing first
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 2
        assert tool_results[0]["tool"] == "slow_tool"
        assert tool_results[1]["tool"] == "fast_tool"

    @pytest.mark.asyncio
    async def test_cancellation_before_parallel_batch(self):
        """Cancellation before parallel batch stubs all tools and returns."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        tc2 = _mock_tool_call("tool_b", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])

        bot = _make_bot()
        session_id = uuid.uuid4()

        dispatch_mock = AsyncMock(return_value=ToolCallResult(
            result="ok",
            result_for_llm='{"ok": true}',
            tool_event={"type": "tool_result", "tool": "tool_a", "result": "ok"},
        ))

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", dispatch_mock), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()), \
             patch("app.agent.loop.session_locks") as mock_locks:
            # Cancel is requested from the start
            mock_locks.is_cancel_requested.return_value = True
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "cancel me"}], bot,
                session_id=session_id,
            ):
                events.append(event)

        # Dispatch should never be called
        dispatch_mock.assert_not_awaited()
        # Should have a cancelled event
        assert any(e["type"] == "cancelled" for e in events)

    @pytest.mark.asyncio
    async def test_cancellation_during_parallel_dispatch(self):
        """When cancellation is detected during parallel dispatch, remaining results are stubbed."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        tc2 = _mock_tool_call("tool_b", '{}', "tc_2")
        tc3 = _mock_tool_call("tool_c", '{}', "tc_3")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2, tc3])

        bot = _make_bot()
        session_id = uuid.uuid4()

        cancel_after_first = {"count": 0}

        # Mock session_locks: cancel is requested after the first tool starts
        def _is_cancel_requested(sid):
            cancel_after_first["count"] += 1
            # First call (pre-batch check) returns False, second+ (inside _dispatch_one) returns True
            return cancel_after_first["count"] > 1

        async def _slow_dispatch(**kwargs):
            await asyncio.sleep(0.02)
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_slow_dispatch), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()), \
             patch("app.agent.loop.session_locks") as mock_locks:
            mock_locks.is_cancel_requested.side_effect = _is_cancel_requested
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "cancel during batch"}], bot,
                session_id=session_id,
            ):
                events.append(event)

        assert any(e["type"] == "cancelled" for e in events)

    @pytest.mark.asyncio
    async def test_tool_error_doesnt_block_others(self):
        """One tool raising an exception doesn't prevent other tools from completing."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("good_tool", '{}', "tc_1")
        tc2 = _mock_tool_call("bad_tool", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()

        async def _dispatch_with_error(**kwargs):
            if kwargs["name"] == "bad_tool":
                # dispatch_tool_call catches errors internally and returns an error ToolCallResult
                return ToolCallResult(
                    result="Error: something went wrong",
                    result_for_llm='{"error": "something went wrong"}',
                    tool_event={"type": "tool_result", "tool": "bad_tool", "error": "something went wrong"},
                )
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": "good_tool", "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_dispatch_with_error), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "mixed tools"}], bot
            ):
                events.append(event)

        # Both tools should have results
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 2
        assert tool_results[0]["tool"] == "good_tool"
        assert tool_results[1]["tool"] == "bad_tool"

        # Should have final response
        response_events = [e for e in events if e["type"] == "response"]
        assert len(response_events) == 1

    @pytest.mark.asyncio
    async def test_approval_gate_handled_during_assembly(self):
        """Approval gates are processed sequentially during result assembly."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("normal_tool", '{}', "tc_1")
        tc2 = _mock_tool_call("gated_tool", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()

        async def _dispatch_with_approval(**kwargs):
            if kwargs["name"] == "gated_tool" and not kwargs.get("skip_policy"):
                return ToolCallResult(
                    result="",
                    result_for_llm="",
                    tool_event={},
                    needs_approval=True,
                    approval_id="approval-123",
                    approval_timeout=5,
                    approval_reason="Dangerous tool",
                )
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_dispatch_with_approval), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()), \
             patch("app.agent.approval_pending.create_approval_pending") as mock_create_approval:
            # Simulate approval being granted
            approval_future = asyncio.get_event_loop().create_future()
            approval_future.set_result("approved")
            mock_create_approval.return_value = approval_future

            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "gated request"}], bot
            ):
                events.append(event)

        # Should have approval_request and approval_resolved events
        assert any(e["type"] == "approval_request" for e in events)
        assert any(e["type"] == "approval_resolved" for e in events)

        # Both tools should have results
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 2

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Semaphore should limit concurrent dispatches to PARALLEL_TOOL_MAX_CONCURRENT."""
        from app.agent.loop import run_agent_tool_loop

        # Create 5 tool calls with max_concurrent=2
        tool_calls = [_mock_tool_call(f"tool_{i}", '{}', f"tc_{i}") for i in range(5)]
        acc_tools = _mock_accumulated(content=None, tool_calls=tool_calls)
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()
        max_concurrent_seen = {"value": 0}
        current_concurrent = {"value": 0}

        async def _track_concurrency(**kwargs):
            current_concurrent["value"] += 1
            if current_concurrent["value"] > max_concurrent_seen["value"]:
                max_concurrent_seen["value"] = current_concurrent["value"]
            await asyncio.sleep(0.05)
            current_concurrent["value"] -= 1
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_track_concurrency), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings(PARALLEL_TOOL_MAX_CONCURRENT=2)):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "5 tools at once"}], bot
            ):
                events.append(event)

        # Should never exceed the semaphore limit
        assert max_concurrent_seen["value"] <= 2
        # All 5 tools should still complete
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 5

    @pytest.mark.asyncio
    async def test_all_tool_start_events_emitted_upfront(self):
        """In parallel mode, all tool_start events should be emitted before any tool_result."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        tc2 = _mock_tool_call("tool_b", '{}', "tc_2")
        tc3 = _mock_tool_call("tool_c", '{}', "tc_3")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2, tc3])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()

        async def _quick_dispatch(**kwargs):
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_quick_dispatch), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "three tools"}], bot
            ):
                events.append(event)

        # Extract tool_start and tool_result event indices
        tool_event_types = [(i, e["type"]) for i, e in enumerate(events) if e["type"] in ("tool_start", "tool_result")]
        start_indices = [i for i, t in tool_event_types if t == "tool_start"]
        result_indices = [i for i, t in tool_event_types if t == "tool_result"]

        # All starts should come before all results
        assert max(start_indices) < min(result_indices)

    @pytest.mark.asyncio
    async def test_unhandled_exception_doesnt_crash_gather(self):
        """If dispatch_tool_call raises an unhandled exception, the other tools still complete."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("good_tool", '{}', "tc_1")
        tc2 = _mock_tool_call("exploding_tool", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()

        async def _dispatch_with_exception(**kwargs):
            if kwargs["name"] == "exploding_tool":
                raise RuntimeError("Unexpected kaboom")
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": "good_tool", "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_dispatch_with_exception), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "mixed tools"}], bot
            ):
                events.append(event)

        # Both tools should have results — the exploding one gets an error result
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 2
        assert tool_results[0]["tool"] == "good_tool"
        assert tool_results[1]["tool"] == "exploding_tool"
        assert "error" in tool_results[1]

        # Should still get final response
        assert any(e["type"] == "response" for e in events)

    @pytest.mark.asyncio
    async def test_completed_tools_kept_before_cancellation(self):
        """Tools that finished before cancellation keep their real results in messages."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("fast_tool", '{}', "tc_1")
        tc2 = _mock_tool_call("slow_tool", '{}', "tc_2")
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])

        bot = _make_bot()
        session_id = uuid.uuid4()
        messages = [{"role": "user", "content": "test"}]

        cancel_state = {"cancelled": False, "check_count": 0}

        def _is_cancel(sid):
            cancel_state["check_count"] += 1
            return cancel_state["cancelled"]

        async def _dispatch(**kwargs):
            if kwargs["name"] == "slow_tool":
                # Cancellation happens while slow_tool is "running" but since
                # cancellation check is before dispatch, this completes normally.
                # The cancel flag is set for checks that happen AFTER this dispatch.
                cancel_state["cancelled"] = True
                await asyncio.sleep(0.01)
            return ToolCallResult(
                result=f'{{"tool": "{kwargs["name"]}"}}',
                result_for_llm=f'{{"result": "{kwargs["name"]}_result"}}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": f"{kwargs['name']}_result"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_dispatch), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings", _default_mock_settings()), \
             patch("app.agent.loop.session_locks") as mock_locks:
            mock_locks.is_cancel_requested.side_effect = _is_cancel
            events = []
            async for event in run_agent_tool_loop(
                messages, bot, session_id=session_id,
            ):
                events.append(event)

        # Both tools completed (cancellation set during dispatch, not before).
        # Since all dispatches started before cancellation, no was_cancelled=True.
        # The results are kept for both tools.
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) == 2
        assert tool_results[0]["tool"] == "fast_tool"
        assert tool_results[1]["tool"] == "slow_tool"

    @pytest.mark.asyncio
    async def test_client_tools_force_sequential_dispatch(self):
        """Batches containing client tools should use sequential dispatch, not parallel."""
        from app.agent.loop import run_agent_tool_loop

        tc1 = _mock_tool_call("local_tool", '{}', "tc_1")
        tc2 = _mock_tool_call("shell_exec", '{}', "tc_2")  # client tool
        acc_tools = _mock_accumulated(content=None, tool_calls=[tc1, tc2])
        acc_final = _mock_accumulated("Done")

        bot = _make_bot()

        dispatch_times = []

        async def _track_dispatch(**kwargs):
            dispatch_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            return ToolCallResult(
                result="ok",
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"], "result": "ok"},
            )

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tools, acc_final)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.dispatch_tool_call", side_effect=_track_dispatch), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.is_client_tool", side_effect=lambda n: n == "shell_exec"), \
             patch("app.agent.loop.settings", _default_mock_settings()):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "run both"}], bot
            ):
                events.append(event)

        # Sequential: second dispatch starts after first completes (~50ms gap)
        assert len(dispatch_times) == 2
        assert dispatch_times[1] - dispatch_times[0] >= 0.04

        # Sequential path interleaves start/result events
        tool_events = [e for e in events if e["type"] in ("tool_start", "tool_result")]
        assert [e["type"] for e in tool_events] == ["tool_start", "tool_result", "tool_start", "tool_result"]
