"""Priority 3 tests for app.agent.loop — LLM retry, tool dispatch, agent tool loop."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.agent.llm import AccumulatedMessage, _model_cooldowns


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    """Ensure cooldowns don't leak between tests."""
    _model_cooldowns.clear()
    yield
    _model_cooldowns.clear()


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _mock_response(content="Hello", tool_calls=None):
    """Build a mock ChatCompletion response (for _llm_call non-streaming tests)."""
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


def _mock_accumulated(content="Hello", tool_calls=None, completion_tokens=50):
    """Build an AccumulatedMessage for mocking _llm_call_stream."""
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


async def _fake_stream(*accumulated_messages):
    """Return a factory that produces async generators yielding AccumulatedMessage objects.

    Each call to the returned function pops the next message from the list.
    """
    _msgs = list(accumulated_messages)
    _call_idx = 0

    async def _gen(*args, **kwargs):
        nonlocal _call_idx
        if _call_idx < len(_msgs):
            msg = _msgs[_call_idx]
            _call_idx += 1
        else:
            msg = _msgs[-1]
        yield msg

    return _gen


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

def _default_mock_settings(**overrides):
    """Return a mock settings object with defaults for LLM retry/fallback."""
    s = MagicMock()
    defaults = dict(
        LLM_MAX_RETRIES=3,
        LLM_RATE_LIMIT_INITIAL_WAIT=1,
        LLM_RETRY_INITIAL_WAIT=1,
        LLM_FALLBACK_MODEL="",
        LLM_FALLBACK_COOLDOWN_SECONDS=300,
        AGENT_TRACE=False,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


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
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
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
             patch("app.agent.llm.settings", _default_mock_settings(LLM_MAX_RETRIES=2)), \
             patch("asyncio.sleep", new_callable=AsyncMock):
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
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("asyncio.sleep", new_callable=AsyncMock):
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
             patch("app.agent.llm.settings", _default_mock_settings(LLM_RATE_LIMIT_INITIAL_WAIT=10)), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _llm_call("gpt-4", [], None, None)
            # First retry: 10 * 2^0 = 10, second: 10 * 2^1 = 20
            assert mock_sleep.await_args_list[0].args == (10,)
            assert mock_sleep.await_args_list[1].args == (20,)

    @pytest.mark.asyncio
    async def test_retries_on_5xx_server_error(self):
        """5xx errors (InternalServerError) should be retried with shorter backoff."""
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        server_err = openai.InternalServerError(
            message="internal server error",
            response=MagicMock(status_code=500),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[server_err, mock_resp]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings(LLM_RETRY_INITIAL_WAIT=2)), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await _llm_call("gpt-4", [], None, None)
            assert result is mock_resp
            assert mock_client.chat.completions.create.await_count == 2
            mock_sleep.assert_awaited_once_with(2)  # 2 * 2^0

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        """APIConnectionError should be retried."""
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("ok")
        conn_err = openai.APIConnectionError(request=MagicMock())
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[conn_err, mock_resp]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _llm_call("gpt-4", [], None, None)
            assert result is mock_resp

    @pytest.mark.asyncio
    async def test_fallback_model_triggered_after_max_retries(self):
        """After primary model exhausts retries, fallback model should be tried."""
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        mock_resp = _mock_response("fallback ok")
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        call_count = 0
        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("model") == "gpt-4":
                raise rate_err
            return mock_resp

        mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.record_usage"), \
             patch("app.agent.llm.settings", _default_mock_settings(
                 LLM_MAX_RETRIES=1,
             )), \
             patch("app.services.server_config.get_global_fallback_models",
                   return_value=[{"model": "gpt-3.5-turbo"}]), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _llm_call("gpt-4", [], None, None)
            assert result is mock_resp
            # primary: 1 initial + 1 retry = 2, then fallback: 1 call
            assert mock_client.chat.completions.create.await_count == 3

    @pytest.mark.asyncio
    async def test_permanent_error_raised_after_all_attempts(self):
        """If both primary and fallback fail, the error should propagate."""
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=rate_err)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.agent.llm.settings", _default_mock_settings(
                 LLM_MAX_RETRIES=1,
             )), \
             patch("app.services.server_config.get_global_fallback_models",
                   return_value=[{"model": "gpt-3.5-turbo"}]), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(openai.RateLimitError):
                await _llm_call("gpt-4", [], None, None)
            # primary: 2 attempts, fallback: 2 attempts
            assert mock_client.chat.completions.create.await_count == 4

    @pytest.mark.asyncio
    async def test_no_fallback_when_not_configured(self):
        """With no fallbacks configured, error should raise immediately after retries."""
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        server_err = openai.InternalServerError(
            message="server error",
            response=MagicMock(status_code=500),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=server_err)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.agent.llm.settings", _default_mock_settings(
                 LLM_MAX_RETRIES=1,
             )), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(openai.InternalServerError):
                await _llm_call("gpt-4", [], None, None)
            # Only primary attempts: 1 initial + 1 retry = 2
            assert mock_client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_no_fallback_when_same_as_primary(self):
        """Fallback should be skipped when it's the same model as primary."""
        from app.agent.loop import _llm_call

        mock_client = AsyncMock()
        server_err = openai.InternalServerError(
            message="server error",
            response=MagicMock(status_code=500),
            body=None,
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=server_err)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.agent.llm.settings", _default_mock_settings(
                 LLM_MAX_RETRIES=1,
             )), \
             patch("app.services.server_config.get_global_fallback_models",
                   return_value=[{"model": "gpt-4"}]), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(openai.InternalServerError):
                await _llm_call("gpt-4", [], None, None)
            assert mock_client.chat.completions.create.await_count == 2


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
        acc1 = _mock_accumulated(content=None, tool_calls=[tc])
        acc2 = _mock_accumulated("done")

        bot = _make_bot(local_tools=["my_local_tool"])

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc1, acc2)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}') as mock_call, \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
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
        acc1 = _mock_accumulated(content=None, tool_calls=[tc])
        acc2 = _mock_accumulated("done")

        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc1, acc2)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=True), \
             patch("app.agent.tool_dispatch.get_mcp_server_for_tool", return_value="my_server"), \
             patch("app.agent.tool_dispatch.call_mcp_tool", new_callable=AsyncMock, return_value='{"ok": true}') as mock_call, \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
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
        acc1 = _mock_accumulated(content=None, tool_calls=[tc])
        acc2 = _mock_accumulated("done")

        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc1, acc2)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
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

        acc = _mock_accumulated("Hello world")
        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc)), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                events.append(event)

            response_events = [e for e in events if e["type"] == "response"]
            assert len(response_events) == 1
            assert response_events[0]["text"] == "Hello world"

    @pytest.mark.asyncio
    async def test_max_iterations_guard(self):
        """LLM always returns tool calls — loop should terminate at AGENT_MAX_ITERATIONS."""
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("some_tool", '{}', "tc_1")
        acc_tool = _mock_accumulated(content=None, tool_calls=[tc])

        # The forced final call uses _llm_call (non-streaming), so we mock that too.
        final_resp = _mock_response("forced response")

        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tool, acc_tool, acc_tool)), \
             patch("app.agent.loop._llm_call", new_callable=AsyncMock, return_value=final_resp), \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
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

        acc = _mock_accumulated("summary done")
        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc)), \
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

    @pytest.mark.asyncio
    async def test_silent_completion_after_tool_calls(self):
        """After tool calls, empty LLM response should be accepted silently (no forced retry)."""
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("some_tool", '{}', "tc_1")
        acc_tool = _mock_accumulated(content=None, tool_calls=[tc])
        acc_empty = _mock_accumulated(content="")  # empty text, no tool calls

        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tool, acc_empty)), \
             patch("app.agent.loop._llm_call", new_callable=AsyncMock) as mock_llm_call, \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop.settings") as mock_settings:
            mock_settings.AGENT_MAX_ITERATIONS = 10
            mock_settings.AGENT_TRACE = False
            mock_settings.TOOL_RESULT_SUMMARIZE_ENABLED = False
            mock_settings.TOOL_RESULT_SUMMARIZE_THRESHOLD = 99999
            mock_settings.TOOL_RESULT_SUMMARIZE_MODEL = ""
            mock_settings.TOOL_RESULT_SUMMARIZE_MAX_TOKENS = 500
            mock_settings.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS = []

            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "do stuff"}], bot
            ):
                events.append(event)

            # Should get a response event with empty text
            response_events = [e for e in events if e["type"] == "response"]
            assert len(response_events) == 1
            assert response_events[0]["text"] == ""

            # No warning or error events should be emitted
            warning_events = [e for e in events if e["type"] == "warning"]
            error_events = [e for e in events if e["type"] == "error"]
            assert len(warning_events) == 0
            assert len(error_events) == 0

            # Forced retry (_llm_call non-streaming) should NOT be called
            mock_llm_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_forced_retry_when_no_tool_calls_made(self):
        """Empty response with zero tool calls ever made should trigger forced retry."""
        from app.agent.loop import run_agent_tool_loop

        acc_empty = _mock_accumulated(content="")  # empty text, no tool calls

        final_resp = _mock_response("forced response")
        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_empty)), \
             patch("app.agent.loop._llm_call", new_callable=AsyncMock, return_value=final_resp) as mock_llm_call, \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "hi"}], bot
            ):
                events.append(event)

            # Warning event with empty_response code should be emitted
            warning_events = [e for e in events if e["type"] == "warning"]
            assert len(warning_events) == 1
            assert warning_events[0]["code"] == "empty_response"

            # Forced retry should have been called
            mock_llm_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zero_completion_tokens_triggers_retry_despite_tool_calls(self):
        """0 completion tokens after tool calls = model API glitch, NOT intentional silence.

        Regression test: previously the "silent completion" path accepted ANY empty
        response when tool_calls_made was truthy, even if completion_tokens was 0
        (indicating the model didn't generate anything at all).
        """
        from app.agent.loop import run_agent_tool_loop

        tc = _mock_tool_call("some_tool", '{}', "tc_1")
        acc_tool = _mock_accumulated(content=None, tool_calls=[tc])
        # Key: completion_tokens=0 means the model didn't generate anything
        acc_zero = _mock_accumulated(content="", completion_tokens=0)

        final_resp = _mock_response("Here is the actual response")
        bot = _make_bot()

        with patch("app.agent.loop._llm_call_stream", side_effect=_make_stream_side_effects(acc_tool, acc_zero)), \
             patch("app.agent.loop._llm_call", new_callable=AsyncMock, return_value=final_resp) as mock_llm_call, \
             patch("app.services.providers.check_rate_limit", return_value=0), \
             patch("app.agent.loop.get_local_tool_schemas", return_value=[]), \
             patch("app.agent.loop.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]), \
             patch("app.agent.loop.get_client_tool_schemas", return_value=[]), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
             patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock, return_value=None), \
             patch("app.agent.loop._record_trace_event", new_callable=AsyncMock, return_value=None):
            events = []
            async for event in run_agent_tool_loop(
                [{"role": "user", "content": "check the cameras"}], bot
            ):
                events.append(event)

            # Warning event should be emitted (not silently swallowed)
            warning_events = [e for e in events if e["type"] == "warning"]
            assert len(warning_events) == 1
            assert warning_events[0]["code"] == "empty_response"
            assert "0 completion tokens" in warning_events[0]["message"]

            # Forced retry should have been called
            mock_llm_call.assert_awaited_once()

            # Final response should contain the retry text
            response_events = [e for e in events if e["type"] == "response"]
            assert len(response_events) == 1
            assert response_events[0]["text"] == "Here is the actual response"
