"""Priority 3 tests for app.agent.loop — LLM retry, tool dispatch, agent tool loop."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import openai
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
    """Build a mock ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls or []
    choice.finish_reason = "stop" if not tool_calls else "tool_calls"
    # model_dump should return a dict without None values
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
# _llm_call tests
# ---------------------------------------------------------------------------

class TestLlmCall:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"):
            result = await _llm_call("gpt-4", [{"role": "user", "content": "hi"}], None, None)
            assert result is mock_resp
            mock_client.chat.completions.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_then_succeeds(self):
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[rate_err, mock_resp]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings") as mock_settings, \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_settings.LLM_RATE_LIMIT_RETRIES = 3
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 1
            mock_settings.AGENT_TRACE = False
            result = await _llm_call("gpt-4", [], None, None)
            assert result is mock_resp
            assert mock_client.chat.completions.create.await_count == 2
            mock_sleep.assert_awaited_once_with(1)  # 1 * 2^0

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=rate_err)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.agent.llm.settings") as mock_settings, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_settings.LLM_RATE_LIMIT_RETRIES = 2
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 1
            mock_settings.AGENT_TRACE = False
            with pytest.raises(openai.RateLimitError):
                await _llm_call("gpt-4", [], None, None)
            assert mock_client.chat.completions.create.await_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        timeout_err = openai.APITimeoutError(request=MagicMock())
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[timeout_err, mock_resp]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings") as mock_settings, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_settings.LLM_RATE_LIMIT_RETRIES = 3
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 1
            mock_settings.AGENT_TRACE = False
            result = await _llm_call("gpt-4", [], None, None)
            assert result is mock_resp

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[rate_err, rate_err, mock_resp]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings") as mock_settings, \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_settings.LLM_RATE_LIMIT_RETRIES = 3
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 10
            mock_settings.AGENT_TRACE = False
            await _llm_call("gpt-4", [], None, None)
            # First retry: 10 * 2^0 = 10, second: 10 * 2^1 = 20
            assert mock_sleep.await_args_list[0].args == (10,)
            assert mock_sleep.await_args_list[1].args == (20,)


# ---------------------------------------------------------------------------
# _summarize_tool_result tests
# ---------------------------------------------------------------------------

class TestSummarizeToolResult:
    @pytest.mark.asyncio
    async def test_returns_summary_on_success(self):
        from app.agent.loop import _summarize_tool_result

        mock_client = AsyncMock()
        summary_resp = _mock_response("Key findings: X, Y, Z")
        mock_client.chat.completions.create = AsyncMock(return_value=summary_resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await _summarize_tool_result("my_tool", "a" * 5000, "gpt-4", 500)
            assert "[summarized from 5,000 chars]" in result
            assert "Key findings: X, Y, Z" in result

    @pytest.mark.asyncio
    async def test_returns_original_on_error(self):
        from app.agent.loop import _summarize_tool_result

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("fail"))

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            original = "original content"
            result = await _summarize_tool_result("my_tool", original, "gpt-4", 500)
            assert result == original


# ---------------------------------------------------------------------------
# Tool dispatch routing tests
# ---------------------------------------------------------------------------

class TestToolDispatchRouting:
    @pytest.mark.asyncio
    async def test_local_tool_dispatched(self):
        """Mock LLM to return a local tool call then text. Verify call_local_tool called."""
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("my_local_tool", '{"x": 1}', "tc_1")
        resp1 = _mock_response(content=None, tool_calls=[tc])
        resp2 = _mock_response("done")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

        bot = _make_bot(local_tools=["my_local_tool"])

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.is_client_tool", return_value=False), \
             patch("app.agent.loop.is_local_tool", return_value=True), \
             patch("app.agent.loop.is_mcp_tool", return_value=False), \
             patch("app.agent.loop.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}') as mock_call, \
             patch("app.agent.loop._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "test"}], bot
            ):
                events.append(event)

            mock_call.assert_awaited_once_with("my_local_tool", '{"x": 1}')
            event_types = [e["type"] for e in events]
            assert "tool_start" in event_types
            assert "tool_result" in event_types
            assert "response" in event_types

    @pytest.mark.asyncio
    async def test_mcp_tool_dispatched(self):
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("mcp_action", '{}', "tc_1")
        resp1 = _mock_response(content=None, tool_calls=[tc])
        resp2 = _mock_response("done")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

        bot = _make_bot()

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.is_client_tool", return_value=False), \
             patch("app.agent.loop.is_local_tool", return_value=False), \
             patch("app.agent.loop.is_mcp_tool", return_value=True), \
             patch("app.agent.loop.get_mcp_server_for_tool", return_value="my_server"), \
             patch("app.agent.loop.call_mcp_tool", new_callable=AsyncMock, return_value='{"ok": true}') as mock_call, \
             patch("app.agent.loop._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "test"}], bot
            ):
                events.append(event)

            mock_call.assert_awaited_once_with("mcp_action", '{}')

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("nonexistent_tool", '{}', "tc_1")
        resp1 = _mock_response(content=None, tool_calls=[tc])
        resp2 = _mock_response("done")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

        bot = _make_bot()

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.is_client_tool", return_value=False), \
             patch("app.agent.loop.is_local_tool", return_value=False), \
             patch("app.agent.loop.is_mcp_tool", return_value=False), \
             patch("app.agent.loop._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "test"}], bot
            ):
                events.append(event)
            # Should have a tool_result event with an error
            tool_results = [e for e in events if e["type"] == "tool_result"]
            assert len(tool_results) == 1
            assert "error" in tool_results[0]


# ---------------------------------------------------------------------------
# run_agent_tool_loop orchestration tests
# ---------------------------------------------------------------------------

class TestRunAgentToolLoop:
    @pytest.mark.asyncio
    async def test_single_iteration_no_tools(self):
        """LLM returns text response immediately — loop yields response and terminates."""
        from app.agent.loop import run_agent_tool_loop

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_response("Hello world")
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
                [{"role": "user", "content": "hi"}], bot
            ):
                events.append(event)

            assert len(events) == 1
            assert events[0]["type"] == "response"
            assert events[0]["text"] == "Hello world"

    @pytest.mark.asyncio
    async def test_max_iterations_guard(self):
        """LLM always returns tool calls — loop should terminate at AGENT_MAX_ITERATIONS."""
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("some_tool", '{}', "tc_1")

        mock_client = AsyncMock()
        # All calls return tool calls, except the forced final one
        tool_resp = _mock_response(content=None, tool_calls=[tc])
        final_resp = _mock_response("forced response")
        # We need max_iterations tool responses + 1 forced response
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[tool_resp] * 3 + [final_resp]
        )

        bot = _make_bot()

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop.is_client_tool", return_value=False), \
             patch("app.agent.loop.is_local_tool", return_value=True), \
             patch("app.agent.loop.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.loop._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings") as mock_settings:
            mock_settings.AGENT_MAX_ITERATIONS = 3
            mock_settings.AGENT_TRACE = False
            mock_settings.TOOL_RESULT_SUMMARIZE_ENABLED = False
            mock_settings.TOOL_RESULT_SUMMARIZE_THRESHOLD = 99999
            mock_settings.TOOL_RESULT_SUMMARIZE_MODEL = ""
            mock_settings.TOOL_RESULT_SUMMARIZE_MAX_TOKENS = 500
            mock_settings.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS = []

            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "loop forever"}], bot
            ):
                events.append(event)

            response_events = [e for e in events if e["type"] == "response"]
            assert len(response_events) == 1
            assert response_events[0]["text"] == "forced response"

    @pytest.mark.asyncio
    async def test_compaction_tag_added(self):
        """When compaction=True, yielded events should have compaction=True."""
        from app.agent.loop import run_agent_tool_loop

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_response("summary done")
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
                compaction=True,
            ):
                events.append(event)

            assert all(e.get("compaction") is True for e in events)
