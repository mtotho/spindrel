"""Tests for supports_tools flag: DB cache, heuristic fallback, and LLM tool stripping."""
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.llm import AccumulatedMessage, _is_tools_not_supported_error, _llm_call_stream
from app.agent.model_params import (
    _HEURISTIC_NO_TOOLS_MODELS,
    _HEURISTIC_NO_TOOLS_PATTERNS,
)
from app.services.providers import model_supports_tools


# ---------------------------------------------------------------------------
# _HEURISTIC_NO_TOOLS_MODELS / _HEURISTIC_NO_TOOLS_PATTERNS integrity
# ---------------------------------------------------------------------------

class TestHeuristicNoToolsSets:
    def test_known_image_gen_models_in_set(self):
        assert "gemini-2.0-flash-exp-image-generation" in _HEURISTIC_NO_TOOLS_MODELS
        assert "imagen-3.0-generate-002" in _HEURISTIC_NO_TOOLS_MODELS

    def test_standard_models_not_in_set(self):
        for m in ("gpt-4o", "gemini/gemini-2.5-flash", "anthropic/claude-3-opus"):
            assert m not in _HEURISTIC_NO_TOOLS_MODELS

    def test_image_generation_pattern_present(self):
        assert "image-generation" in _HEURISTIC_NO_TOOLS_PATTERNS

    def test_gemini_image_patterns_present(self):
        """Gemini native image models (flash-image, pro-image) should be in patterns."""
        assert "flash-image" in _HEURISTIC_NO_TOOLS_PATTERNS
        assert "pro-image" in _HEURISTIC_NO_TOOLS_PATTERNS


# ---------------------------------------------------------------------------
# model_supports_tools — DB cache path
# ---------------------------------------------------------------------------

class TestModelSupportsToolsDB:
    def test_flagged_db_model_returns_false(self):
        """Models in _no_tools_models cache should return False."""
        with patch("app.services.providers._no_tools_models", {"my-image-model"}):
            assert model_supports_tools("my-image-model") is False

    def test_unflagged_db_model_returns_true(self):
        with patch("app.services.providers._no_tools_models", set()):
            assert model_supports_tools("gpt-4o") is True


# ---------------------------------------------------------------------------
# model_supports_tools — heuristic fallback
# ---------------------------------------------------------------------------

class TestModelSupportsToolsHeuristic:
    def test_exact_match_heuristic(self):
        """Exact model IDs in the heuristic set should return False."""
        with patch("app.services.providers._no_tools_models", set()):
            assert model_supports_tools("gemini-2.0-flash-exp-image-generation") is False
            assert model_supports_tools("imagen-3.0-generate-002") is False

    def test_pattern_match_heuristic(self):
        """Models containing a heuristic pattern substring should return False."""
        with patch("app.services.providers._no_tools_models", set()):
            assert model_supports_tools("some-future-image-generation-model") is False

    def test_gemini_flash_image_no_tools(self):
        """Gemini native image generation models should not support tools."""
        with patch("app.services.providers._no_tools_models", set()):
            assert model_supports_tools("gemini/gemini-2.5-flash-image") is False
            assert model_supports_tools("gemini/gemini-2.5-pro-image") is False
            assert model_supports_tools("gemini/gemini-2.0-flash-image") is False

    def test_gpt_image_models_support_tools(self):
        """OpenAI gpt-image models DO support tools — patterns must not match them."""
        with patch("app.services.providers._no_tools_models", set()):
            assert model_supports_tools("gpt-image-1") is True

    def test_normal_model_returns_true(self):
        """Normal models should return True (supports tools)."""
        with patch("app.services.providers._no_tools_models", set()):
            assert model_supports_tools("gpt-4o") is True
            assert model_supports_tools("gemini/gemini-2.5-flash") is True
            assert model_supports_tools("anthropic/claude-3-opus") is True

    def test_db_flag_takes_priority(self):
        """DB flag should be checked before heuristic."""
        # Flag a normal model as no-tools in DB cache
        with patch("app.services.providers._no_tools_models", {"gpt-4o"}):
            assert model_supports_tools("gpt-4o") is False


# ---------------------------------------------------------------------------
# _is_tools_not_supported_error — error message detection
# ---------------------------------------------------------------------------

class TestIsToolsNotSupportedError:
    def _make_bad_request(self, message: str):
        """Build a mock BadRequestError with a given message."""
        import openai
        import httpx
        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        response = httpx.Response(status_code=400, text=message, request=request)
        return openai.BadRequestError(message=message, response=response, body=None)

    def test_function_calling_message(self):
        exc = self._make_bad_request("This model does not support function calling")
        assert _is_tools_not_supported_error(exc) is True

    def test_tools_not_supported_message(self):
        exc = self._make_bad_request("tools are not supported for this model")
        assert _is_tools_not_supported_error(exc) is True

    def test_does_not_support_tools_message(self):
        exc = self._make_bad_request("model does not support tools")
        assert _is_tools_not_supported_error(exc) is True

    def test_tool_use_not_supported_message(self):
        exc = self._make_bad_request("tool use is not supported")
        assert _is_tools_not_supported_error(exc) is True

    def test_unrelated_400_not_matched(self):
        exc = self._make_bad_request("Invalid model parameter: temperature must be between 0 and 2")
        assert _is_tools_not_supported_error(exc) is False

    def test_empty_message_not_matched(self):
        exc = self._make_bad_request("")
        assert _is_tools_not_supported_error(exc) is False


# ---------------------------------------------------------------------------
# Helpers for LLM integration tests
# ---------------------------------------------------------------------------

def _make_chunk(content=None, finish_reason=None, usage=None):
    chunk = MagicMock()
    if content is None and finish_reason is None:
        if usage is not None:
            chunk.choices = []
            chunk.usage = usage
            return chunk
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = None
    delta.reasoning_content = None
    delta.reasoning = None
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


async def _async_iter(items):
    for item in items:
        yield item


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


def _make_bad_request_error(message: str):
    import httpx
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status_code=400, text=message, request=request)
    return openai.BadRequestError(message=message, response=response, body=None)


# ---------------------------------------------------------------------------
# Proactive tool stripping in _llm_call_stream
# ---------------------------------------------------------------------------

class TestProactiveToolStripping:
    @pytest.mark.asyncio
    async def test_tools_stripped_when_model_does_not_support_tools(self):
        """When model_supports_tools returns False, tools/tool_choice should be None in the API call."""
        chunks = [
            _make_chunk(content="I can't use tools"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.providers.model_supports_tools", return_value=False), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            async for item in _llm_call_stream("image-gen-model", [{"role": "user", "content": "hi"}], tools, "auto"):
                items.append(item)

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "I can't use tools"

        # Verify tools/tool_choice were NOT passed to the API at all (not even as None)
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "tools" not in call_kwargs, "tools should be omitted, not passed as None"
        assert "tool_choice" not in call_kwargs, "tool_choice should be omitted, not passed as None"

    @pytest.mark.asyncio
    async def test_tools_passed_when_model_supports_tools(self):
        """When model_supports_tools returns True, tools should be passed through."""
        chunks = [
            _make_chunk(content="ok"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.providers.model_supports_tools", return_value=True), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            async for item in _llm_call_stream("gpt-4", [{"role": "user", "content": "hi"}], tools, "auto"):
                items.append(item)

        # Verify the API was called with tools passed through
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("tools") == tools or call_kwargs[1].get("tools") == tools


# ---------------------------------------------------------------------------
# Reactive 400 retry in _llm_call_stream
# ---------------------------------------------------------------------------

class TestReactive400Retry:
    @pytest.mark.asyncio
    async def test_bad_request_tools_error_retries_without_tools(self):
        """A 400 with 'tools not supported' message should trigger one retry without tools."""
        bad_err = _make_bad_request_error("This model does not support function calling")
        chunks = [
            _make_chunk(content="text response"),
            _make_chunk(finish_reason="stop"),
        ]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[bad_err, _async_iter(chunks)]
        )

        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.providers.model_supports_tools", return_value=True), \
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            items = []
            async for item in _llm_call_stream("some-model", [{"role": "user", "content": "hi"}], tools, "auto"):
                items.append(item)

        msg = items[-1]
        assert isinstance(msg, AccumulatedMessage)
        assert msg.content == "text response"

        # Should have been called twice: first with tools, second without
        assert mock_client.chat.completions.create.await_count == 2
        second_call_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert "tools" not in second_call_kwargs, "tools should be omitted on retry, not passed as None"

    @pytest.mark.asyncio
    async def test_unrelated_bad_request_raises(self):
        """A 400 that's NOT about tools should propagate as-is."""
        bad_err = _make_bad_request_error("Invalid temperature value")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=bad_err)

        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.providers.model_supports_tools", return_value=True), \
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            with pytest.raises(openai.BadRequestError):
                async for _ in _llm_call_stream("some-model", [{"role": "user", "content": "hi"}], tools, "auto"):
                    pass

    @pytest.mark.asyncio
    async def test_bad_request_no_tools_in_request_raises(self):
        """A 400 with tools message but no tools were sent should propagate (no retry)."""
        bad_err = _make_bad_request_error("tools are not supported")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=bad_err)

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.providers.requires_system_message_folding", return_value=False), \
             patch("app.services.providers.model_supports_tools", return_value=True), \
             patch("app.agent.llm.settings", _default_mock_settings()), \
             patch("app.services.server_config.get_global_fallback_models", return_value=[]):
            with pytest.raises(openai.BadRequestError):
                async for _ in _llm_call_stream("some-model", [{"role": "user", "content": "hi"}], None, None):
                    pass
