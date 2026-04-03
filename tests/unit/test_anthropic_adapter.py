"""Tests for the Anthropic → OpenAI adapter (app/services/anthropic_adapter.py)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.anthropic_adapter import (
    AnthropicOpenAIAdapter,
    _StreamAdapter,
    _build_usage,
    _merge_consecutive_roles,
    _message_to_completion,
    _translate_exception,
    _translate_messages,
    _translate_tool_choice,
    _translate_tools,
    _translate_stop_reason,
    _DEFAULT_MAX_TOKENS,
)


# ---------------------------------------------------------------------------
# Message translation
# ---------------------------------------------------------------------------


class TestTranslateMessages:
    def test_simple_user_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        system, result = _translate_messages(msgs)
        assert system == ""
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    def test_system_message_extracted(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, result = _translate_messages(msgs)
        # Single system message without cache_control collapses to plain string
        assert system == "You are helpful."
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_multiple_system_messages_merged(self):
        msgs = [
            {"role": "system", "content": "First system."},
            {"role": "system", "content": "Second system."},
            {"role": "user", "content": "Hi"},
        ]
        system, result = _translate_messages(msgs)
        assert isinstance(system, list)
        assert len(system) == 2
        assert system[0]["text"] == "First system."
        assert system[1]["text"] == "Second system."

    def test_system_with_cache_control_preserved(self):
        msgs = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "Cached system prompt",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "user", "content": "Hi"},
        ]
        system, result = _translate_messages(msgs)
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_assistant_with_tool_calls(self):
        msgs = [
            {"role": "user", "content": "Search for cats"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query": "cats"}',
                        },
                    }
                ],
            },
        ]
        system, result = _translate_messages(msgs)
        assert len(result) == 2
        assert result[1]["role"] == "assistant"
        blocks = result[1]["content"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "tool_use"
        assert blocks[0]["name"] == "web_search"
        assert blocks[0]["input"] == {"query": "cats"}
        assert blocks[0]["id"] == "call_1"

    def test_assistant_with_content_and_tool_calls(self):
        msgs = [
            {"role": "user", "content": "Search"},
            {
                "role": "assistant",
                "content": "Let me search for that.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            },
        ]
        _, result = _translate_messages(msgs)
        blocks = result[1]["content"]
        assert len(blocks) == 2
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "Let me search for that."
        assert blocks[1]["type"] == "tool_use"

    def test_tool_result_merged_into_user(self):
        msgs = [
            {"role": "user", "content": "Search"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "Result here"},
        ]
        _, result = _translate_messages(msgs)
        # tool result should be in a user message
        assert result[-1]["role"] == "user"
        content = result[-1]["content"]
        assert isinstance(content, list)
        assert any(b["type"] == "tool_result" for b in content)
        tool_result = [b for b in content if b["type"] == "tool_result"][0]
        assert tool_result["tool_use_id"] == "call_1"
        assert tool_result["content"] == "Result here"

    def test_multiple_tool_results_merged(self):
        msgs = [
            {"role": "user", "content": "Do two things"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "Result 1"},
            {"role": "tool", "tool_call_id": "c2", "content": "Result 2"},
        ]
        _, result = _translate_messages(msgs)
        # Both tool results should be in the same user message
        last_user = result[-1]
        assert last_user["role"] == "user"
        tool_results = [b for b in last_user["content"] if b["type"] == "tool_result"]
        assert len(tool_results) == 2

    def test_empty_messages(self):
        system, result = _translate_messages([])
        assert system == ""
        assert result == []

    def test_tool_result_without_preceding_user(self):
        """Tool result not preceded by a user message creates a new user message."""
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "Result"},
        ]
        _, result = _translate_messages(msgs)
        assert result[-1]["role"] == "user"


# ---------------------------------------------------------------------------
# Consecutive role merging
# ---------------------------------------------------------------------------


class TestMergeConsecutiveRoles:
    def test_no_merge_needed(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        assert _merge_consecutive_roles(msgs) == msgs

    def test_merge_consecutive_user_strings(self):
        msgs = [
            {"role": "user", "content": "Part 1"},
            {"role": "user", "content": "Part 2"},
        ]
        result = _merge_consecutive_roles(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "Part 1\nPart 2"

    def test_merge_consecutive_user_blocks(self):
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "A"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "B"}]},
        ]
        result = _merge_consecutive_roles(msgs)
        assert len(result) == 1
        assert len(result[0]["content"]) == 2

    def test_empty_list(self):
        assert _merge_consecutive_roles([]) == []


# ---------------------------------------------------------------------------
# Tool translation
# ---------------------------------------------------------------------------


class TestTranslateTools:
    def test_basic_tool(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ]
        result = _translate_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "web_search"
        assert result[0]["description"] == "Search the web"
        assert result[0]["input_schema"]["properties"]["query"]["type"] == "string"

    def test_tool_without_parameters(self):
        tools = [
            {
                "type": "function",
                "function": {"name": "get_time", "description": "Get current time"},
            }
        ]
        result = _translate_tools(tools)
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_none_tools(self):
        assert _translate_tools(None) is None

    def test_empty_tools(self):
        assert _translate_tools([]) is None

    def test_multiple_tools(self):
        tools = [
            {"type": "function", "function": {"name": "a", "description": "A", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "b", "description": "B", "parameters": {"type": "object", "properties": {}}}},
        ]
        result = _translate_tools(tools)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "b"


# ---------------------------------------------------------------------------
# Tool choice translation
# ---------------------------------------------------------------------------


class TestTranslateToolChoice:
    def test_auto(self):
        assert _translate_tool_choice("auto") == {"type": "auto"}

    def test_none_string(self):
        assert _translate_tool_choice("none") is None

    def test_required(self):
        assert _translate_tool_choice("required") == {"type": "any"}

    def test_none_value(self):
        assert _translate_tool_choice(None) == {"type": "auto"}

    def test_specific_function(self):
        result = _translate_tool_choice({"type": "function", "function": {"name": "search"}})
        assert result == {"type": "tool", "name": "search"}


# ---------------------------------------------------------------------------
# Stop reason translation
# ---------------------------------------------------------------------------


class TestTranslateStopReason:
    def test_end_turn(self):
        assert _translate_stop_reason("end_turn") == "stop"

    def test_tool_use(self):
        assert _translate_stop_reason("tool_use") == "tool_calls"

    def test_max_tokens(self):
        assert _translate_stop_reason("max_tokens") == "length"

    def test_stop_sequence(self):
        assert _translate_stop_reason("stop_sequence") == "stop"

    def test_none(self):
        assert _translate_stop_reason(None) == "stop"


# ---------------------------------------------------------------------------
# Usage translation
# ---------------------------------------------------------------------------


class TestBuildUsage:
    def test_basic_usage(self):
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_read_input_tokens = 20
        mock_usage.cache_creation_input_tokens = 10
        usage = _build_usage(mock_usage)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150
        assert usage.prompt_tokens_details.cached_tokens == 30

    def test_usage_without_cache(self):
        mock_usage = MagicMock()
        mock_usage.input_tokens = 50
        mock_usage.output_tokens = 25
        mock_usage.cache_read_input_tokens = 0
        mock_usage.cache_creation_input_tokens = 0
        usage = _build_usage(mock_usage)
        assert usage.prompt_tokens_details.cached_tokens == 0

    def test_usage_none_fields(self):
        mock_usage = MagicMock()
        mock_usage.input_tokens = None
        mock_usage.output_tokens = None
        mock_usage.cache_read_input_tokens = None
        mock_usage.cache_creation_input_tokens = None
        usage = _build_usage(mock_usage)
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0


# ---------------------------------------------------------------------------
# Non-streaming response translation
# ---------------------------------------------------------------------------


class TestMessageToCompletion:
    def test_text_response(self):
        msg = MagicMock()
        msg.id = "msg_123"
        msg.model = "claude-sonnet-4-6"
        msg.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello!"
        msg.content = [text_block]
        msg.usage = MagicMock(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)

        completion = _message_to_completion(msg)
        assert completion.id == "msg_123"
        assert completion.model == "claude-sonnet-4-6"
        assert len(completion.choices) == 1
        assert completion.choices[0].message.content == "Hello!"
        assert completion.choices[0].message.tool_calls is None
        assert completion.choices[0].finish_reason == "stop"

    def test_tool_use_response(self):
        msg = MagicMock()
        msg.id = "msg_456"
        msg.model = "claude-sonnet-4-6"
        msg.stop_reason = "tool_use"
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_123"
        tool_block.name = "web_search"
        tool_block.input = {"query": "cats"}
        msg.content = [tool_block]
        msg.usage = MagicMock(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)

        completion = _message_to_completion(msg)
        assert completion.choices[0].finish_reason == "tool_calls"
        tcs = completion.choices[0].message.tool_calls
        assert len(tcs) == 1
        assert tcs[0].id == "toolu_123"
        assert tcs[0].function.name == "web_search"
        assert json.loads(tcs[0].function.arguments) == {"query": "cats"}

    def test_mixed_text_and_tool_use(self):
        msg = MagicMock()
        msg.id = "msg_789"
        msg.model = "claude-sonnet-4-6"
        msg.stop_reason = "tool_use"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Let me search."
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_abc"
        tool_block.name = "search"
        tool_block.input = {}
        msg.content = [text_block, tool_block]
        msg.usage = MagicMock(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)

        completion = _message_to_completion(msg)
        assert completion.choices[0].message.content == "Let me search."
        assert len(completion.choices[0].message.tool_calls) == 1


# ---------------------------------------------------------------------------
# Streaming translation
# ---------------------------------------------------------------------------


class TestStreamAdapter:
    """Test the _StreamAdapter that translates Anthropic stream events to OpenAI chunks."""

    def _make_event(self, type: str, **kwargs) -> MagicMock:
        event = MagicMock()
        event.type = type
        for k, v in kwargs.items():
            setattr(event, k, v)
        return event

    def test_translate_message_start(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = ""
        adapter._model = "claude-sonnet-4-6"
        adapter._tool_index = -1

        msg = MagicMock()
        msg.id = "msg_001"
        msg.usage = MagicMock(input_tokens=10, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        event = self._make_event("message_start", message=msg)

        chunks = adapter._translate_event(event)
        assert len(chunks) == 1
        assert adapter._message_id == "msg_001"
        assert chunks[0].choices[0].delta.role == "assistant"
        assert chunks[0].usage is not None
        assert chunks[0].usage.prompt_tokens == 10

    def test_translate_text_delta(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = "msg_001"
        adapter._model = "test"
        adapter._tool_index = -1

        delta = MagicMock()
        delta.type = "text_delta"
        delta.text = "Hello"
        event = self._make_event("content_block_delta", delta=delta)

        chunks = adapter._translate_event(event)
        assert len(chunks) == 1
        assert chunks[0].choices[0].delta.content == "Hello"

    def test_translate_tool_use_start(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = "msg_001"
        adapter._model = "test"
        adapter._tool_index = -1
        adapter._input_json_buf = ""

        block = MagicMock()
        block.type = "tool_use"
        block.id = "toolu_abc"
        block.name = "web_search"
        event = self._make_event("content_block_start", content_block=block)

        chunks = adapter._translate_event(event)
        assert len(chunks) == 1
        tc = chunks[0].choices[0].delta.tool_calls[0]
        assert tc.id == "toolu_abc"
        assert tc.function.name == "web_search"
        assert tc.index == 0
        assert adapter._tool_index == 0

    def test_translate_input_json_delta(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = "msg_001"
        adapter._model = "test"
        adapter._tool_index = 0
        adapter._input_json_buf = ""

        delta = MagicMock()
        delta.type = "input_json_delta"
        delta.partial_json = '{"query":'
        event = self._make_event("content_block_delta", delta=delta)

        chunks = adapter._translate_event(event)
        assert len(chunks) == 1
        tc = chunks[0].choices[0].delta.tool_calls[0]
        assert tc.function.arguments == '{"query":'
        assert tc.index == 0

    def test_translate_message_delta_stop(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = "msg_001"
        adapter._model = "test"
        adapter._tool_index = -1

        delta = MagicMock()
        delta.stop_reason = "end_turn"
        usage = MagicMock(input_tokens=10, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        # Anthropic's message_delta has output_tokens in usage
        event = self._make_event("message_delta", delta=delta, usage=usage)

        chunks = adapter._translate_event(event)
        assert len(chunks) == 1
        assert chunks[0].choices[0].finish_reason == "stop"

    def test_translate_tool_use_stop(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = "msg_001"
        adapter._model = "test"
        adapter._tool_index = 0

        delta = MagicMock()
        delta.stop_reason = "tool_use"
        usage = MagicMock(input_tokens=10, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        event = self._make_event("message_delta", delta=delta, usage=usage)

        chunks = adapter._translate_event(event)
        assert chunks[0].choices[0].finish_reason == "tool_calls"

    def test_content_block_stop_noop(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = "msg_001"
        adapter._model = "test"
        adapter._tool_index = -1

        event = self._make_event("content_block_stop")
        chunks = adapter._translate_event(event)
        assert chunks == []

    def test_message_stop_noop(self):
        adapter = _StreamAdapter.__new__(_StreamAdapter)
        adapter._message_id = "msg_001"
        adapter._model = "test"
        adapter._tool_index = -1

        event = self._make_event("message_stop")
        chunks = adapter._translate_event(event)
        assert chunks == []


# ---------------------------------------------------------------------------
# Completions.create() integration
# ---------------------------------------------------------------------------


class TestCompletionsCreate:
    @pytest.mark.asyncio
    async def test_non_streaming_call(self):
        """Non-streaming create() should translate and return a ChatCompletion."""
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        # Mock the underlying Anthropic client
        mock_response = MagicMock()
        mock_response.id = "msg_test"
        mock_response.model = "claude-sonnet-4-6"
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hi there!"
        mock_response.content = [text_block]
        mock_response.usage = MagicMock(
            input_tokens=50, output_tokens=10,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )

        adapter._anthropic.messages.create = AsyncMock(return_value=mock_response)

        result = await adapter.chat.completions.create(
            model="claude-sonnet-4-6",
            messages=[
                {"role": "system", "content": "Be helpful."},
                {"role": "user", "content": "Hello"},
            ],
            stream=False,
        )

        assert result.id == "msg_test"
        assert result.choices[0].message.content == "Hi there!"
        assert result.choices[0].finish_reason == "stop"
        assert result.usage.prompt_tokens == 50

        # Verify the Anthropic SDK was called with correct args
        call_kwargs = adapter._anthropic.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["max_tokens"] == _DEFAULT_MAX_TOKENS
        assert "system" in call_kwargs

    @pytest.mark.asyncio
    async def test_streaming_call_returns_stream_adapter(self):
        """Streaming create() should return a _StreamAdapter."""
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        mock_stream_ctx = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
        mock_manager.__aexit__ = AsyncMock(return_value=False)
        adapter._anthropic.messages.stream = MagicMock(return_value=mock_manager)

        result = await adapter.chat.completions.create(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            stream=True,
        )

        assert isinstance(result, _StreamAdapter)

    @pytest.mark.asyncio
    async def test_tools_translated(self):
        """Tools should be translated from OpenAI format to Anthropic format."""
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.id = "msg_t"
        mock_response.model = "claude-sonnet-4-6"
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "OK"
        mock_response.content = [text_block]
        mock_response.usage = MagicMock(
            input_tokens=10, output_tokens=5,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )

        adapter._anthropic.messages.create = AsyncMock(return_value=mock_response)

        await adapter.chat.completions.create(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }],
            tool_choice="auto",
            stream=False,
        )

        call_kwargs = adapter._anthropic.messages.create.call_args[1]
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0]["name"] == "search"
        assert call_kwargs["tools"][0]["input_schema"]["properties"]["q"]["type"] == "string"
        assert call_kwargs["tool_choice"] == {"type": "auto"}

    @pytest.mark.asyncio
    async def test_max_tokens_default(self):
        """max_tokens should default to _DEFAULT_MAX_TOKENS if not specified."""
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.id = "msg_t"
        mock_response.model = "test"
        mock_response.stop_reason = "end_turn"
        mock_response.content = []
        mock_response.usage = MagicMock(
            input_tokens=0, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )

        adapter._anthropic.messages.create = AsyncMock(return_value=mock_response)

        await adapter.chat.completions.create(
            model="test",
            messages=[{"role": "user", "content": "Hi"}],
            stream=False,
        )

        call_kwargs = adapter._anthropic.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == _DEFAULT_MAX_TOKENS

    @pytest.mark.asyncio
    async def test_max_tokens_passthrough(self):
        """Explicit max_tokens should be passed through."""
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.id = "msg_t"
        mock_response.model = "test"
        mock_response.stop_reason = "end_turn"
        mock_response.content = []
        mock_response.usage = MagicMock(
            input_tokens=0, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )

        adapter._anthropic.messages.create = AsyncMock(return_value=mock_response)

        await adapter.chat.completions.create(
            model="test",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=4096,
            stream=False,
        )

        call_kwargs = adapter._anthropic.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_temperature_passthrough(self):
        """Temperature should be passed through."""
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.id = "msg_t"
        mock_response.model = "test"
        mock_response.stop_reason = "end_turn"
        mock_response.content = []
        mock_response.usage = MagicMock(
            input_tokens=0, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )

        adapter._anthropic.messages.create = AsyncMock(return_value=mock_response)

        await adapter.chat.completions.create(
            model="test",
            messages=[{"role": "user", "content": "Hi"}],
            temperature=0.7,
            stream=False,
        )

        call_kwargs = adapter._anthropic.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_tool_choice_none_omits_tools(self):
        """tool_choice='none' should not send tool_choice (Anthropic: omit to disable)."""
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.id = "msg_t"
        mock_response.model = "test"
        mock_response.stop_reason = "end_turn"
        mock_response.content = []
        mock_response.usage = MagicMock(
            input_tokens=0, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )

        adapter._anthropic.messages.create = AsyncMock(return_value=mock_response)

        await adapter.chat.completions.create(
            model="test",
            messages=[{"role": "user", "content": "Hi"}],
            tools=[{
                "type": "function",
                "function": {"name": "x", "description": "x", "parameters": {"type": "object", "properties": {}}},
            }],
            tool_choice="none",
            stream=False,
        )

        call_kwargs = adapter._anthropic.messages.create.call_args[1]
        # tool_choice should not be in kwargs when "none"
        assert "tool_choice" not in call_kwargs


# ---------------------------------------------------------------------------
# Adapter construction
# ---------------------------------------------------------------------------


class TestAdapterConstruction:
    def test_default_base_url(self):
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")
        assert adapter.base_url == "https://api.anthropic.com"

    def test_custom_base_url(self):
        adapter = AnthropicOpenAIAdapter(api_key="sk-test", base_url="https://custom.api.com/v1")
        assert adapter.base_url == "https://custom.api.com/v1"
        # The internal client should strip /v1
        assert str(adapter._anthropic.base_url).rstrip("/").endswith("custom.api.com")

    def test_has_chat_completions_interface(self):
        adapter = AnthropicOpenAIAdapter(api_key="sk-test")
        assert hasattr(adapter, "chat")
        assert hasattr(adapter.chat, "completions")
        assert hasattr(adapter.chat.completions, "create")


# ---------------------------------------------------------------------------
# StreamAccumulator compatibility
# ---------------------------------------------------------------------------


class TestStreamAccumulatorCompat:
    """Verify that adapter chunks are compatible with llm.py's StreamAccumulator."""

    def test_text_chunk_has_expected_structure(self):
        """A text delta chunk should work with StreamAccumulator.feed()."""
        from app.agent.llm import StreamAccumulator

        acc = StreamAccumulator()

        # Simulate a message_start chunk
        chunk1 = _make_text_chunk("msg_1", role="assistant")
        events, done = acc.feed(chunk1)
        assert not done

        # Simulate a text content chunk
        chunk2 = _make_text_chunk("msg_1", content="Hello world")
        events, done = acc.feed(chunk2)
        assert any(e["type"] == "text_delta" for e in events)
        assert not done

        # Simulate finish
        chunk3 = _make_text_chunk("msg_1", finish_reason="stop")
        events, done = acc.feed(chunk3)
        assert done

        msg = acc.build()
        assert msg.content == "Hello world"
        assert msg.tool_calls is None

    def test_tool_call_chunk_has_expected_structure(self):
        """Tool call chunks should accumulate correctly in StreamAccumulator."""
        from app.agent.llm import StreamAccumulator

        acc = StreamAccumulator()

        # role chunk
        acc.feed(_make_text_chunk("msg_1", role="assistant"))

        # tool_call start
        from app.services.anthropic_adapter import _ChatCompletionChunk, _Choice, _ChoiceDelta, _ToolCall, _Function
        tc_start = _ChatCompletionChunk(
            id="msg_1", model="test", choices=[_Choice(
                delta=_ChoiceDelta(tool_calls=[_ToolCall(
                    id="toolu_abc", type="function",
                    function=_Function(name="search", arguments=""),
                    index=0,
                )]),
            )],
        )
        acc.feed(tc_start)

        # tool_call arguments
        tc_args = _ChatCompletionChunk(
            id="msg_1", model="test", choices=[_Choice(
                delta=_ChoiceDelta(tool_calls=[_ToolCall(
                    id="", type="function",
                    function=_Function(name="", arguments='{"q":"cats"}'),
                    index=0,
                )]),
            )],
        )
        acc.feed(tc_args)

        # finish
        finish = _ChatCompletionChunk(
            id="msg_1", model="test", choices=[_Choice(
                finish_reason="tool_calls",
                delta=_ChoiceDelta(),
            )],
        )
        events, done = acc.feed(finish)
        assert done

        msg = acc.build()
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["function"]["name"] == "search"
        assert msg.tool_calls[0]["function"]["arguments"] == '{"q":"cats"}'
        assert msg.tool_calls[0]["id"] == "toolu_abc"

    def test_usage_chunk_picked_up(self):
        """Usage from the adapter should be picked up by StreamAccumulator."""
        from app.agent.llm import StreamAccumulator
        from app.services.anthropic_adapter import _ChatCompletionChunk, _Choice, _ChoiceDelta, _Usage, _PromptTokensDetails

        acc = StreamAccumulator()

        # Message start with usage
        start = _ChatCompletionChunk(
            id="msg_1", model="test",
            choices=[_Choice(delta=_ChoiceDelta(role="assistant"))],
            usage=_Usage(prompt_tokens=100, completion_tokens=0, total_tokens=100,
                         prompt_tokens_details=_PromptTokensDetails(cached_tokens=50)),
        )
        acc.feed(start)

        # Text
        acc.feed(_make_text_chunk("msg_1", content="Hi"))

        # Finish with updated usage
        finish = _ChatCompletionChunk(
            id="msg_1", model="test",
            choices=[_Choice(finish_reason="stop", delta=_ChoiceDelta())],
            usage=_Usage(prompt_tokens=100, completion_tokens=5, total_tokens=105,
                         prompt_tokens_details=_PromptTokensDetails(cached_tokens=50)),
        )
        acc.feed(finish)

        msg = acc.build()
        assert msg.usage is not None
        assert msg.usage.prompt_tokens == 100
        assert msg.usage.completion_tokens == 5
        assert msg.cached_tokens == 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_chunk(
    msg_id: str,
    content: str | None = None,
    role: str | None = None,
    finish_reason: str | None = None,
) -> Any:
    """Build an OpenAI-shaped chunk using our adapter dataclasses."""
    from app.services.anthropic_adapter import _ChatCompletionChunk, _Choice, _ChoiceDelta
    delta = _ChoiceDelta(role=role, content=content)
    return _ChatCompletionChunk(
        id=msg_id,
        model="test",
        choices=[_Choice(delta=delta, finish_reason=finish_reason)],
    )


# ---------------------------------------------------------------------------
# Exception translation
# ---------------------------------------------------------------------------


class TestExceptionTranslation:
    """Verify Anthropic SDK exceptions are translated to openai equivalents."""

    def _mock_response(self, status_code: int = 400) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.headers = {}
        resp.request = MagicMock()
        return resp

    def test_rate_limit_error(self):
        import anthropic
        import openai

        resp = self._mock_response(429)
        exc = anthropic.RateLimitError(
            message="rate limited", response=resp, body={"error": {"message": "rate limited"}},
        )
        translated = _translate_exception(exc)
        assert isinstance(translated, openai.RateLimitError)

    def test_bad_request_error(self):
        import anthropic
        import openai

        resp = self._mock_response(400)
        exc = anthropic.BadRequestError(
            message="bad request", response=resp, body={"error": {"message": "bad request"}},
        )
        translated = _translate_exception(exc)
        assert isinstance(translated, openai.BadRequestError)

    def test_authentication_error(self):
        import anthropic
        import openai

        resp = self._mock_response(401)
        exc = anthropic.AuthenticationError(
            message="unauthorized", response=resp, body={"error": {"message": "unauthorized"}},
        )
        translated = _translate_exception(exc)
        assert isinstance(translated, openai.AuthenticationError)

    def test_internal_server_error(self):
        import anthropic
        import openai

        resp = self._mock_response(500)
        exc = anthropic.InternalServerError(
            message="server error", response=resp, body={"error": {"message": "server error"}},
        )
        translated = _translate_exception(exc)
        assert isinstance(translated, openai.InternalServerError)

    def test_timeout_error(self):
        import anthropic
        import openai

        exc = anthropic.APITimeoutError(request=MagicMock())
        translated = _translate_exception(exc)
        assert isinstance(translated, openai.APITimeoutError)

    def test_connection_error(self):
        import anthropic
        import openai

        exc = anthropic.APIConnectionError(message="connection refused", request=MagicMock())
        translated = _translate_exception(exc)
        assert isinstance(translated, openai.APIConnectionError)

    def test_unknown_exception_passthrough(self):
        """Non-anthropic exceptions pass through unchanged."""
        exc = ValueError("not an anthropic error")
        assert _translate_exception(exc) is exc

    @pytest.mark.asyncio
    async def test_non_streaming_translates_exceptions(self):
        """Non-streaming create() should raise openai exceptions."""
        import anthropic
        import openai

        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        resp = self._mock_response(429)
        adapter._anthropic.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited", response=resp, body={},
            ),
        )

        with pytest.raises(openai.RateLimitError):
            await adapter.chat.completions.create(
                model="test",
                messages=[{"role": "user", "content": "Hi"}],
                stream=False,
            )

    @pytest.mark.asyncio
    async def test_streaming_create_translates_exceptions(self):
        """Streaming create() should raise openai exceptions on connect."""
        import anthropic
        import openai

        adapter = AnthropicOpenAIAdapter(api_key="sk-test")

        resp = self._mock_response(429)
        mock_manager = MagicMock()
        mock_manager.__aenter__ = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited", response=resp, body={},
            ),
        )
        adapter._anthropic.messages.stream = MagicMock(return_value=mock_manager)

        with pytest.raises(openai.RateLimitError):
            await adapter.chat.completions.create(
                model="test",
                messages=[{"role": "user", "content": "Hi"}],
                stream=True,
            )
