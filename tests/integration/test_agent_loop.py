"""Integration tests for app.agent.loop — LLM call retry, tool dispatch, agent tool loop."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.agent.llm import AccumulatedMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test-bot",
        name="Test Bot",
        model="test/model",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(enabled=False),
        knowledge=KnowledgeConfig(enabled=False),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _mock_response(content="Hello", tool_calls=None):
    """Build a mock OpenAI ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls or []
    choice.message.model_dump.return_value = {
        "role": "assistant",
        "content": content,
        **({"tool_calls": [_tc_dict(tc) for tc in tool_calls]} if tool_calls else {}),
    }
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    return resp


def _tc_dict(tc):
    return {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}


def _make_tool_call(tc_id="tc_1", name="echo", arguments='{"text": "hi"}'):
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _mock_accumulated(content="Hello", tool_calls=None):
    """Build an AccumulatedMessage for mocking _llm_call_stream."""
    tc_list = None
    if tool_calls:
        tc_list = [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ]
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150
    return AccumulatedMessage(
        content=content,
        tool_calls=tc_list,
        usage=usage,
    )


def _make_stream_side_effects(*accumulated_messages):
    """Create a side_effect function for patching _llm_call_stream.
    Each invocation yields the next AccumulatedMessage in order.
    """
    _msgs = list(accumulated_messages)
    _idx = {"n": 0}

    async def _stream(*args, **kwargs):
        idx = _idx["n"]
        _idx["n"] += 1
        msg = _msgs[idx] if idx < len(_msgs) else _msgs[-1]
        yield msg

    return _stream


# ---------------------------------------------------------------------------
# _llm_call tests
# ---------------------------------------------------------------------------

class TestLlmCall:
    """Test retry logic in _llm_call."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        mock_client = AsyncMock()
        expected = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(return_value=expected)

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.providers.record_usage"),
        ):
            from app.agent.loop import _llm_call
            result = await _llm_call("test/model", [{"role": "user", "content": "hi"}], None, None)

        assert result is expected
        assert mock_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self):
        mock_client = AsyncMock()
        error = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        success = _mock_response("recovered")
        mock_client.chat.completions.create = AsyncMock(side_effect=[error, success])

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.providers.record_usage"),
            patch("app.agent.llm.settings") as mock_settings,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.LLM_MAX_RETRIES = 3
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 1
            from app.agent.loop import _llm_call
            result = await _llm_call("test/model", [{"role": "user", "content": "hi"}], None, None)

        assert result is success
        assert mock_client.chat.completions.create.call_count == 2
        mock_sleep.assert_called_once_with(1)  # 1 * 2^0

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        mock_client = AsyncMock()
        error = openai.APITimeoutError(request=MagicMock())
        success = _mock_response("recovered")
        mock_client.chat.completions.create = AsyncMock(side_effect=[error, success])

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.providers.record_usage"),
            patch("app.agent.llm.settings") as mock_settings,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.LLM_MAX_RETRIES = 3
            mock_settings.LLM_RETRY_INITIAL_WAIT = 2
            from app.agent.loop import _llm_call
            result = await _llm_call("test/model", [], None, None)

        assert result is success
        mock_sleep.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        mock_client = AsyncMock()
        error = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=error)

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.agent.llm.settings") as mock_settings,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.LLM_MAX_RETRIES = 2
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 1
            mock_settings.LLM_FALLBACK_MODEL = None
            from app.agent.loop import _llm_call
            with pytest.raises(openai.RateLimitError):
                await _llm_call("test/model", [], None, None)

        # 1 initial + 2 retries = 3 total calls
        assert mock_client.chat.completions.create.call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self):
        mock_client = AsyncMock()
        error = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        success = _mock_response("ok")
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[error, error, success]
        )

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.providers.record_usage"),
            patch("app.agent.llm.settings") as mock_settings,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.LLM_MAX_RETRIES = 3
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 5
            from app.agent.loop import _llm_call
            await _llm_call("test/model", [], None, None)

        # Backoff: 5*2^0=5, 5*2^1=10
        assert mock_sleep.call_args_list[0][0][0] == 5
        assert mock_sleep.call_args_list[1][0][0] == 10


# ---------------------------------------------------------------------------
# _summarize_tool_result tests
# ---------------------------------------------------------------------------

class TestSummarizeToolResult:
    @pytest.mark.asyncio
    async def test_returns_summary_when_successful(self):
        mock_client = AsyncMock()
        resp = _mock_response("Summarized output")
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.agent.loop import _summarize_tool_result
            result = await _summarize_tool_result("my_tool", "x" * 20000, "test/model", 500)

        assert result.startswith("[summarized from 20,000 chars]")
        assert "Summarized output" in result

    @pytest.mark.asyncio
    async def test_falls_back_on_error(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("LLM down"))

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.agent.loop import _summarize_tool_result
            original = "original content"
            result = await _summarize_tool_result("my_tool", original, "test/model", 500)

        assert result == original

    @pytest.mark.asyncio
    async def test_caps_input_at_12k(self):
        mock_client = AsyncMock()
        resp = _mock_response("short")
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        big_content = "x" * 20000
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.agent.loop import _summarize_tool_result
            await _summarize_tool_result("my_tool", big_content, "test/model", 500)

        call_args = mock_client.chat.completions.create.call_args
        prompt_content = call_args[1]["messages"][0]["content"]
        assert "chars omitted" in prompt_content


# ---------------------------------------------------------------------------
# run_agent_tool_loop tests
# ---------------------------------------------------------------------------

class TestRunAgentToolLoop:
    """Test the core agent loop orchestration."""

    @pytest.mark.asyncio
    async def test_single_iteration_no_tools(self):
        """LLM returns text with no tool calls → single response event."""
        bot = _make_bot()
        acc = _mock_accumulated("Hello world")

        with (
            patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
            patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.loop.get_client_tool_schemas", return_value=[]),
            patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc)),
            patch("app.services.providers.check_rate_limit", return_value=0),
        ):
            from app.agent.loop import run_agent_tool_loop
            messages = [{"role": "user", "content": "hi"}]
            events = []
            async for event in run_agent_tool_loop(messages, bot):
                events.append(event)

        response_events = [e for e in events if e["type"] == "response"]
        assert len(response_events) == 1
        assert response_events[0]["text"] == "Hello world"

    @pytest.mark.asyncio
    async def test_tool_call_then_response(self):
        """LLM calls a tool, then returns text."""
        bot = _make_bot()
        tc = _make_tool_call(tc_id="tc_1", name="echo", arguments='{"text": "hi"}')
        acc_with_tool = _mock_accumulated(content=None, tool_calls=[tc])
        acc_final = _mock_accumulated("Done")

        with (
            patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
            patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.loop.get_client_tool_schemas", return_value=[]),
            patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_with_tool, acc_final)),
            patch("app.services.providers.check_rate_limit", return_value=0),
            patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_local_tool", return_value=True),
            patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False),
            patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"result": "echoed"}'),
            patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock),
        ):
            from app.agent.loop import run_agent_tool_loop
            messages = [{"role": "user", "content": "echo hi"}]
            events = []
            async for event in run_agent_tool_loop(messages, bot):
                events.append(event)

        types = [e["type"] for e in events]
        assert "tool_start" in types
        assert "tool_result" in types
        assert types[-1] == "response"
        assert events[-1]["text"] == "Done"

    @pytest.mark.asyncio
    async def test_max_iterations_guard(self):
        """Loop terminates at AGENT_MAX_ITERATIONS and forces a response."""
        bot = _make_bot()
        tc = _make_tool_call()
        acc_tool = _mock_accumulated(content=None, tool_calls=[tc])
        # The forced final call uses _llm_call (non-streaming), so we mock that separately.
        final_resp = _mock_response("Forced answer")

        with (
            patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
            patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.loop.get_client_tool_schemas", return_value=[]),
            patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tool, acc_tool, acc_tool)),
            patch("app.agent.loop._llm_call", new_callable=AsyncMock, return_value=final_resp),
            patch("app.services.providers.check_rate_limit", return_value=0),
            patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_local_tool", return_value=True),
            patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False),
            patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='"ok"'),
            patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock),
            patch("app.agent.loop.settings") as mock_settings,
        ):
            mock_settings.AGENT_MAX_ITERATIONS = 2
            mock_settings.AGENT_TRACE = False
            mock_settings.TOOL_RESULT_SUMMARIZE_ENABLED = False
            mock_settings.TOOL_RESULT_SUMMARIZE_THRESHOLD = 99999
            mock_settings.TOOL_RESULT_SUMMARIZE_MODEL = ""
            mock_settings.TOOL_RESULT_SUMMARIZE_MAX_TOKENS = 500
            mock_settings.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS = []

            from app.agent.loop import run_agent_tool_loop
            messages = [{"role": "user", "content": "loop forever"}]
            events = []
            async for event in run_agent_tool_loop(messages, bot):
                events.append(event)

        response_events = [e for e in events if e["type"] == "response"]
        assert len(response_events) == 1
        assert response_events[0]["text"] == "Forced answer"

    @pytest.mark.asyncio
    async def test_tool_dispatch_mcp(self):
        """MCP tool call is routed to call_mcp_tool."""
        bot = _make_bot()
        tc = _make_tool_call(name="ha_call_service")
        acc_with_tool = _mock_accumulated(content=None, tool_calls=[tc])
        acc_final = _mock_accumulated("Done")

        with (
            patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
            patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.loop.get_client_tool_schemas", return_value=[]),
            patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_with_tool, acc_final)),
            patch("app.services.providers.check_rate_limit", return_value=0),
            patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_local_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_mcp_tool", return_value=True),
            patch("app.agent.tool_dispatch.get_mcp_server_for_tool", return_value="homeassistant"),
            patch("app.agent.tool_dispatch.call_mcp_tool", new_callable=AsyncMock, return_value='{"ok": true}') as mock_mcp,
            patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock),
        ):
            from app.agent.loop import run_agent_tool_loop
            messages = [{"role": "user", "content": "turn on lights"}]
            events = []
            async for event in run_agent_tool_loop(messages, bot):
                events.append(event)

        mock_mcp.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """Unknown tool name returns error JSON in tool result."""
        bot = _make_bot()
        tc = _make_tool_call(name="nonexistent")
        acc_with_tool = _mock_accumulated(content=None, tool_calls=[tc])
        acc_final = _mock_accumulated("Sorry")

        with (
            patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
            patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.loop.get_client_tool_schemas", return_value=[]),
            patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_with_tool, acc_final)),
            patch("app.services.providers.check_rate_limit", return_value=0),
            patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_local_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False),
            patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock),
        ):
            from app.agent.loop import run_agent_tool_loop
            messages = [{"role": "user", "content": "use nonexistent"}]
            events = []
            async for event in run_agent_tool_loop(messages, bot):
                events.append(event)

        tool_events = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_events) == 1
        assert "error" in tool_events[0]

    @pytest.mark.asyncio
    async def test_compaction_flag_tags_events(self):
        """When compaction=True, all yielded events get compaction: True."""
        bot = _make_bot()
        acc = _mock_accumulated("summary")

        with (
            patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
            patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
            patch("app.agent.loop.get_client_tool_schemas", return_value=[]),
            patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc)),
            patch("app.services.providers.check_rate_limit", return_value=0),
        ):
            from app.agent.loop import run_agent_tool_loop
            messages = [{"role": "user", "content": "summarize"}]
            events = []
            async for event in run_agent_tool_loop(messages, bot, compaction=True):
                events.append(event)

        assert all(e.get("compaction") is True for e in events)
