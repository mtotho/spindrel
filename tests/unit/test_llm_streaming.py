"""Tests for _llm_call_stream — streaming LLM call with retry + fallback."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.llm import AccumulatedMessage, _consume_stream, _llm_call_stream, _model_cooldowns


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    _model_cooldowns.clear()
    yield
    _model_cooldowns.clear()


def _make_chunk(content=None, tool_calls=None, finish_reason=None, usage=None, reasoning_content=None):
    """Build a mock streaming chunk."""
    chunk = MagicMock()
    if content is None and tool_calls is None and finish_reason is None and reasoning_content is None:
        if usage is not None:
            chunk.choices = []
            chunk.usage = usage
            return chunk
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    delta.reasoning_content = reasoning_content
    delta.reasoning = None
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


def _default_mock_settings(**overrides):
    s = MagicMock()
    defaults = dict(
        LLM_MAX_RETRIES=3,
        LLM_RATE_LIMIT_INITIAL_WAIT=1,
        LLM_RETRY_INITIAL_WAIT=1,
        LLM_FALLBACK_COOLDOWN_SECONDS=300,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


async def _async_iter(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item


class TestLlmCallStream:
    @pytest.mark.asyncio
    async def test_happy_path_text_stream(self):
        """Stream completes: yields text_delta events then AccumulatedMessage."""
        chunks = [
            _make_chunk(content="Hello "),
            _make_chunk(content="world"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            async for item in _llm_call_stream("gpt-4", [{"role": "user", "content": "hi"}], None, None):
                items.append(item)

        # Should have text_delta events and final AccumulatedMessage
        deltas = [i for i in items if isinstance(i, dict) and i.get("type") == "text_delta"]
        assert len(deltas) == 2
        assert deltas[0]["delta"] == "Hello "
        assert deltas[1]["delta"] == "world"

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "Hello world"

    @pytest.mark.asyncio
    async def test_tool_call_only_no_text_deltas(self):
        """Tool-call-only response should yield no text_delta events."""
        tc_delta = MagicMock()
        tc_delta.index = 0
        tc_delta.id = "tc_1"
        tc_delta.function = MagicMock()
        tc_delta.function.name = "search"
        tc_delta.function.arguments = '{"q": "test"}'

        chunks = [
            _make_chunk(tool_calls=[tc_delta]),
            _make_chunk(finish_reason="tool_calls"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            async for item in _llm_call_stream("gpt-4", [], None, None):
                items.append(item)

        deltas = [i for i in items if isinstance(i, dict) and i.get("type") == "text_delta"]
        assert len(deltas) == 0

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.tool_calls is not None
        assert msg.tool_calls[0]["function"]["name"] == "search"

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Connection error on create() should be retried."""
        conn_err = openai.APIConnectionError(request=MagicMock())
        chunks = [
            _make_chunk(content="ok"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[conn_err, _async_iter(chunks)]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            items = []
            async for item in _llm_call_stream("gpt-4", [], None, None):
                items.append(item)

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "ok"
        assert mock_client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_fallback_after_retries_exhausted(self):
        """After primary retries exhausted, fallback model should be tried."""
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        chunks = [
            _make_chunk(content="fallback ok"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()

        call_count = 0
        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("model") == "gpt-4":
                raise rate_err
            return _async_iter(chunks)

        mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.agent.llm.settings", _default_mock_settings(LLM_MAX_RETRIES=1)), \
             patch("app.services.server_config.get_global_fallback_models",
                   return_value=[{"model": "gpt-3.5-turbo"}]), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            items = []
            async for item in _llm_call_stream("gpt-4", [], None, None,
                                               fallback_models=[{"model": "gpt-3.5-turbo"}]):
                items.append(item)

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "fallback ok"

    @pytest.mark.asyncio
    async def test_usage_captured_from_separate_chunk(self):
        """Usage in a separate chunk after finish_reason must propagate to AccumulatedMessage.

        This is the critical test: with stream_options.include_usage, the provider
        sends usage in a final chunk with empty choices AFTER the finish_reason chunk.
        Without this, token_usage trace events are never recorded.
        """
        usage = MagicMock()
        usage.prompt_tokens = 100
        usage.completion_tokens = 50
        usage.total_tokens = 150

        chunks = [
            _make_chunk(content="Hello"),
            _make_chunk(finish_reason="stop"),
            _make_chunk(usage=usage),  # separate usage-only chunk
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            async for item in _llm_call_stream("gpt-4", [{"role": "user", "content": "hi"}], None, None):
                items.append(item)

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "Hello"
        assert msg.usage is usage
        assert msg.usage.prompt_tokens == 100
        assert msg.usage.completion_tokens == 50

    @pytest.mark.asyncio
    async def test_thinking_content_emitted(self):
        """Thinking/reasoning content should be emitted as events."""
        chunks = [
            _make_chunk(reasoning_content="Let me think..."),
            _make_chunk(content="Here's the answer."),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            async for item in _llm_call_stream("gpt-4", [], None, None):
                items.append(item)

        thinking_events = [i for i in items if isinstance(i, dict) and i.get("type") == "thinking"]
        assert len(thinking_events) == 1
        assert thinking_events[0]["delta"] == "Let me think..."

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.thinking_content == "Let me think..."
        assert msg.content == "Here's the answer."

    @pytest.mark.asyncio
    async def test_tools_none_not_passed_to_api(self):
        """When tools are stripped (force_no_tools), tools=None should NOT be sent to the API.

        Some providers (Vertex/Gemini via LiteLLM) interpret tools=null as
        'enable function calling' and reject models that don't support it.
        """
        chunks = [
            _make_chunk(content="ok"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.providers.model_supports_tools", return_value=False), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            # Pass tools, but model_supports_tools returns False → tools should be stripped
            async for item in _llm_call_stream(
                "gemini/gemini-2.5-flash-image",
                [{"role": "user", "content": "hi"}],
                [{"type": "function", "function": {"name": "test", "parameters": {}}}],
                "auto",
            ):
                items.append(item)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        # tools and tool_choice should NOT be present in kwargs at all
        assert "tools" not in call_kwargs, "tools=None should not be passed to the API"
        assert "tool_choice" not in call_kwargs, "tool_choice=None should not be passed to the API"

    @pytest.mark.asyncio
    async def test_tools_not_supported_retry_failure_falls_to_fallback(self):
        """If retry without tools also fails, the error should fall through to fallback chain."""
        bad_request = openai.BadRequestError(
            message="Function calling is not enabled for this model",
            response=MagicMock(status_code=400),
            body=None,
        )
        # Retry also fails with a different error
        retry_error = openai.BadRequestError(
            message="Some other error on retry",
            response=MagicMock(status_code=400),
            body=None,
        )
        chunks = [
            _make_chunk(content="fallback ok"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()

        call_count = {"n": 0}
        async def side_effect(**kwargs):
            call_count["n"] += 1
            if kwargs.get("model") == "gemini/gemini-2.5-flash":
                if call_count["n"] == 1:
                    raise bad_request
                raise retry_error
            return _async_iter(chunks)

        mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)

        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("app.services.server_config.get_global_fallback_models",
                   return_value=[{"model": "gpt-3.5-turbo"}]):
            items = []
            async for item in _llm_call_stream(
                "gemini/gemini-2.5-flash",
                [{"role": "user", "content": "hi"}],
                tools, "auto",
                fallback_models=[{"model": "gpt-3.5-turbo"}],
            ):
                items.append(item)

        # Should have fallen through to fallback and succeeded
        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "fallback ok"


# ---------------------------------------------------------------------------
# _consume_stream — direct tests
# ---------------------------------------------------------------------------

class TestConsumeStream:
    @pytest.mark.asyncio
    async def test_usage_drain_timeout_closes_stream(self):
        """When provider hangs after finish_reason, timeout fires and stream is closed."""
        async def _hanging_stream():
            yield _make_chunk(content="Hello")
            yield _make_chunk(finish_reason="stop")
            # Simulate a provider that hangs forever after finish_reason
            await asyncio.sleep(999)
            yield _make_chunk()  # never reached

        stream = _hanging_stream()
        items = []
        with patch("app.agent.llm._USAGE_DRAIN_TIMEOUT", 0.1):
            async for item in _consume_stream(stream):
                items.append(item)

        # Should have yielded text_delta event(s) + final AccumulatedMessage
        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "Hello"
        # Usage should be None since the usage chunk never arrived
        assert msg.usage is None
