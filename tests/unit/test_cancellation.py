"""Tests for STOP cancellation of in-progress agent loops."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


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


def _mock_tool_call(name="test_tool", args='{}', tc_id="tc_1"):
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args
    return tc


# ---------------------------------------------------------------------------
# session_locks cancellation tests
# ---------------------------------------------------------------------------

class TestSessionLocksCancellation:
    def test_request_cancel_active_session(self):
        from app.services.session_locks import acquire, release, request_cancel, is_cancel_requested
        sid = uuid.uuid4()
        assert acquire(sid)
        assert request_cancel(sid) is True
        assert is_cancel_requested(sid) is True
        release(sid)

    def test_request_cancel_inactive_session(self):
        from app.services.session_locks import request_cancel, is_cancel_requested
        sid = uuid.uuid4()
        assert request_cancel(sid) is False
        assert is_cancel_requested(sid) is False

    def test_acquire_clears_stale_cancel(self):
        from app.services.session_locks import acquire, release, request_cancel, is_cancel_requested, _cancel_requested
        sid = uuid.uuid4()
        # Simulate a stale cancel flag (manually set)
        _cancel_requested.add(str(sid))
        assert is_cancel_requested(sid) is True
        # acquire should clear it
        assert acquire(sid)
        assert is_cancel_requested(sid) is False
        release(sid)

    def test_release_clears_cancel(self):
        from app.services.session_locks import acquire, release, request_cancel, is_cancel_requested
        sid = uuid.uuid4()
        assert acquire(sid)
        request_cancel(sid)
        assert is_cancel_requested(sid) is True
        release(sid)
        assert is_cancel_requested(sid) is False

    def test_clear_cancel(self):
        from app.services.session_locks import acquire, release, request_cancel, is_cancel_requested, clear_cancel
        sid = uuid.uuid4()
        assert acquire(sid)
        request_cancel(sid)
        assert is_cancel_requested(sid) is True
        clear_cancel(sid)
        assert is_cancel_requested(sid) is False
        release(sid)


# ---------------------------------------------------------------------------
# Agent loop cancellation tests
# ---------------------------------------------------------------------------

class TestAgentLoopCancellation:
    @pytest.mark.asyncio
    async def test_cancel_before_llm_call(self):
        """Cancellation at top of iteration yields cancelled event immediately."""
        from app.agent.loop import run_agent_tool_loop
        from app.services import session_locks

        sid = uuid.uuid4()
        bot = _make_bot()

        # Pre-set cancellation
        session_locks._active.add(str(sid))
        session_locks._cancel_requested.add(str(sid))

        try:
            with patch("app.services.providers.get_llm_client"), \
                 patch("app.services.providers.check_rate_limit", return_value=0), \
                 patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
                 patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
                 patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
                events = []
                async for event in run_agent_tool_loop(
                    [{"role": "user", "content": "test"}], bot,
                    session_id=sid,
                ):
                    events.append(event)

                assert len(events) == 1
                assert events[0]["type"] == "cancelled"
        finally:
            session_locks._active.discard(str(sid))
            session_locks._cancel_requested.discard(str(sid))

    @pytest.mark.asyncio
    async def test_cancel_after_llm_before_tools(self):
        """Cancellation after LLM returns tool calls yields cancelled, no tool_start."""
        from app.agent.loop import run_agent_tool_loop
        from app.services import session_locks

        sid = uuid.uuid4()
        bot = _make_bot()

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        tc2 = _mock_tool_call("tool_b", '{}', "tc_2")
        resp1 = _mock_response(content=None, tool_calls=[tc1, tc2])

        mock_client = AsyncMock()
        # Set cancel flag DURING the LLM call (after checkpoint A but before checkpoint B)
        async def llm_side_effect(**kwargs):
            session_locks._cancel_requested.add(str(sid))
            return resp1
        mock_client.chat.completions.create = AsyncMock(side_effect=llm_side_effect)

        session_locks._active.add(str(sid))

        try:
            with patch("app.services.providers.get_llm_client", return_value=mock_client), \
                 patch("app.services.providers.record_usage"), \
                 patch("app.services.providers.check_rate_limit", return_value=0), \
                 patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
                 patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
                 patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
                 patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):

                events = []
                async for event in run_agent_tool_loop(
                    [{"role": "user", "content": "test"}], bot,
                    session_id=sid,
                ):
                    events.append(event)

                event_types = [e["type"] for e in events]
                assert "cancelled" in event_types
                # No tools should have been dispatched
                assert "tool_start" not in event_types
        finally:
            session_locks._active.discard(str(sid))
            session_locks._cancel_requested.discard(str(sid))

    @pytest.mark.asyncio
    async def test_no_cancel_without_session_id(self):
        """Without session_id, cancellation check is skipped."""
        from app.agent.loop import run_agent_tool_loop

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_response("Hello")
        )
        bot = _make_bot()

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot,
                session_id=None,
            ):
                events.append(event)

            assert events[0]["type"] == "response"

    @pytest.mark.asyncio
    async def test_cancel_mid_tool_loop(self):
        """Cancel after first tool executes but before second."""
        from app.agent.loop import run_agent_tool_loop
        from app.agent.tool_dispatch import ToolCallResult
        from app.services import session_locks

        sid = uuid.uuid4()
        bot = _make_bot()

        tc1 = _mock_tool_call("tool_a", '{}', "tc_1")
        tc2 = _mock_tool_call("tool_b", '{}', "tc_2")
        resp1 = _mock_response(content=None, tool_calls=[tc1, tc2])

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=resp1)

        session_locks._active.add(str(sid))

        # Patch dispatch_tool_call to set cancel flag after first call
        call_count = 0

        async def cancelling_dispatch(**kwargs):
            nonlocal call_count
            call_count += 1
            # Set cancel after first tool dispatch
            session_locks._cancel_requested.add(str(sid))
            return ToolCallResult(
                result='{"ok": true}',
                result_for_llm='{"ok": true}',
                tool_event={"type": "tool_result", "tool": kwargs["name"]},
            )

        try:
            with patch("app.services.providers.get_llm_client", return_value=mock_client), \
                 patch("app.services.providers.record_usage"), \
                 patch("app.services.providers.check_rate_limit", return_value=0), \
                 patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
                 patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
                 patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
                 patch("app.agent.loop.dispatch_tool_call", new_callable=AsyncMock, side_effect=cancelling_dispatch), \
                 patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
                messages = [{"role": "user", "content": "test"}]
                events = []
                async for event in run_agent_tool_loop(
                    messages, bot,
                    session_id=sid,
                ):
                    events.append(event)

                event_types = [e["type"] for e in events]
                # First tool should have started and completed
                assert "tool_start" in event_types
                assert "tool_result" in event_types
                # Should get cancelled
                assert "cancelled" in event_types
                # Only one tool_start (second was cancelled before dispatch)
                assert event_types.count("tool_start") == 1
                # dispatch_tool_call was only called once (second was cancelled)
                assert call_count == 1
        finally:
            session_locks._active.discard(str(sid))
            session_locks._cancel_requested.discard(str(sid))
