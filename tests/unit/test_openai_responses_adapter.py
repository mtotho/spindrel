"""Tests for the OpenAI Responses API adapter (chat.completions → /responses)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from app.services.openai_responses_adapter import (
    OpenAIResponsesAdapter,
    _build_request_body,
    _exc_for_status,
    _response_to_completion,
    _ResponsesStreamAdapter,
    _translate_content,
    _translate_messages,
    _translate_tools,
    _translate_tool_choice,
)


# ---------------------------------------------------------------------------
# Message translation
# ---------------------------------------------------------------------------


class TestTranslateMessages:
    def test_system_becomes_instructions(self):
        instructions, items = _translate_messages(
            [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "hello"},
            ]
        )
        assert instructions == "Be brief."
        assert items == [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]},
        ]

    def test_multiple_system_messages_concat(self):
        instructions, _ = _translate_messages(
            [
                {"role": "system", "content": "First."},
                {"role": "system", "content": "Second."},
                {"role": "user", "content": "hi"},
            ]
        )
        assert "First." in instructions
        assert "Second." in instructions

    def test_assistant_message_plain_text(self):
        _, items = _translate_messages(
            [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ]
        )
        assert items[1] == {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "a"}],
        }

    def test_assistant_tool_call_becomes_function_call_item(self):
        _, items = _translate_messages(
            [
                {"role": "user", "content": "weather?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
                        }
                    ],
                },
            ]
        )
        assert items[1] == {
            "type": "function_call",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": '{"city":"SF"}',
        }

    def test_tool_result_becomes_function_call_output(self):
        _, items = _translate_messages(
            [
                {"role": "tool", "tool_call_id": "call_1", "content": "sunny"},
            ]
        )
        assert items == [
            {"type": "function_call_output", "call_id": "call_1", "output": "sunny"},
        ]

    def test_user_message_with_image_url(self):
        _, items = _translate_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,xxx", "detail": "high"},
                        },
                    ],
                }
            ]
        )
        assert items[0]["content"] == [
            {"type": "input_text", "text": "what is this?"},
            {"type": "input_image", "image_url": "data:image/png;base64,xxx", "detail": "high"},
        ]


# ---------------------------------------------------------------------------
# Tool / tool_choice translation
# ---------------------------------------------------------------------------


class TestTranslateTools:
    def test_function_tool_flattens_schema(self):
        out = _translate_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "add",
                        "description": "add numbers",
                        "parameters": {"type": "object", "properties": {"a": {"type": "number"}}},
                    },
                }
            ]
        )
        assert out == [
            {
                "type": "function",
                "name": "add",
                "description": "add numbers",
                "parameters": {"type": "object", "properties": {"a": {"type": "number"}}},
            }
        ]

    def test_none_returns_none(self):
        assert _translate_tools(None) is None
        assert _translate_tools([]) is None

    def test_tool_choice_named_function(self):
        assert _translate_tool_choice({"type": "function", "function": {"name": "x"}}) == {
            "type": "function",
            "name": "x",
        }

    def test_tool_choice_pass_through_strings(self):
        assert _translate_tool_choice("auto") == "auto"
        assert _translate_tool_choice("required") == "required"
        assert _translate_tool_choice("none") == "none"


# ---------------------------------------------------------------------------
# Request body composition
# ---------------------------------------------------------------------------


class TestBuildRequestBody:
    def test_basic_body(self):
        body = _build_request_body(
            model="gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            tool_choice=None,
            stream=False,
            extra={},
        )
        assert body["model"] == "gpt-5"
        assert body["stream"] is False
        assert body["store"] is False
        assert body["input"][0]["role"] == "user"

    def test_max_tokens_maps_to_max_output_tokens(self):
        body = _build_request_body(
            model="gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            tools=None, tool_choice=None, stream=False,
            extra={"max_tokens": 2048},
        )
        assert body["max_output_tokens"] == 2048

    def test_explicit_max_output_tokens_wins(self):
        body = _build_request_body(
            model="gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            tools=None, tool_choice=None, stream=False,
            extra={"max_tokens": 2048, "max_output_tokens": 512},
        )
        assert body["max_output_tokens"] == 512

    def test_tools_and_tool_choice_included(self):
        body = _build_request_body(
            model="gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
            tool_choice="auto",
            stream=True,
            extra={},
        )
        assert body["tools"][0]["name"] == "f"
        assert body["tool_choice"] == "auto"


# ---------------------------------------------------------------------------
# Response translation
# ---------------------------------------------------------------------------


class TestResponseToCompletion:
    def test_plain_text_response(self):
        resp = {
            "id": "resp_1",
            "model": "gpt-5",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hi back"}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }
        comp = _response_to_completion(resp)
        assert comp.id == "resp_1"
        assert comp.choices[0].message.content == "hi back"
        assert comp.choices[0].message.tool_calls is None
        assert comp.choices[0].finish_reason == "stop"
        assert comp.usage.prompt_tokens == 10
        assert comp.usage.completion_tokens == 3

    def test_tool_call_response(self):
        resp = {
            "id": "resp_1",
            "model": "gpt-5",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "get_weather",
                    "arguments": '{"city":"SF"}',
                }
            ],
            "usage": {"input_tokens": 5, "output_tokens": 8},
        }
        comp = _response_to_completion(resp)
        assert comp.choices[0].finish_reason == "tool_calls"
        tcs = comp.choices[0].message.tool_calls
        assert len(tcs) == 1
        assert tcs[0].id == "call_1"
        assert tcs[0].function.name == "get_weather"
        assert json.loads(tcs[0].function.arguments) == {"city": "SF"}

    def test_incomplete_max_output_tokens_maps_to_length(self):
        resp = {
            "id": "r", "model": "m", "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
        }
        comp = _response_to_completion(resp)
        assert comp.choices[0].finish_reason == "length"


# ---------------------------------------------------------------------------
# Exception translation
# ---------------------------------------------------------------------------


class TestExceptionTranslation:
    def _fake_resp(self, status: int) -> httpx.Response:
        return httpx.Response(status, request=httpx.Request("POST", "https://x/y"))

    def test_401_maps_to_auth_error(self):
        exc = _exc_for_status(401, "msg", self._fake_resp(401), None)
        assert isinstance(exc, openai.AuthenticationError)

    def test_429_maps_to_rate_limit(self):
        exc = _exc_for_status(429, "msg", self._fake_resp(429), None)
        assert isinstance(exc, openai.RateLimitError)

    def test_500_maps_to_internal_server_error(self):
        exc = _exc_for_status(500, "msg", self._fake_resp(500), None)
        assert isinstance(exc, openai.InternalServerError)

    def test_400_maps_to_bad_request(self):
        exc = _exc_for_status(400, "msg", self._fake_resp(400), None)
        assert isinstance(exc, openai.BadRequestError)


# ---------------------------------------------------------------------------
# Streaming: SSE → chunks
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    """Minimal stand-in for httpx.Response supporting aiter_lines + aclose."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.request = httpx.Request("POST", "https://x/y")

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b""

    async def aclose(self) -> None:
        pass


def _event(name: str, payload: dict) -> list[str]:
    return [f"event: {name}", f"data: {json.dumps(payload)}", ""]


class TestStreaming:
    @pytest.mark.asyncio
    async def test_text_delta_becomes_content_delta(self):
        lines: list[str] = []
        lines += _event("response.created", {"type": "response.created", "response": {"id": "r1"}})
        lines += _event(
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "hel"},
        )
        lines += _event(
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "lo"},
        )
        lines += _event(
            "response.completed",
            {"type": "response.completed", "response": {"id": "r1", "usage": {"input_tokens": 2, "output_tokens": 2}}},
        )
        fake = _FakeStreamResponse(lines)
        adapter = _ResponsesStreamAdapter(fake, model="gpt-5")

        deltas: list[str] = []
        finish: str | None = None
        async for chunk in adapter:
            if chunk.choices and chunk.choices[0].delta.content:
                deltas.append(chunk.choices[0].delta.content)
            if chunk.choices and chunk.choices[0].finish_reason:
                finish = chunk.choices[0].finish_reason
        assert "".join(deltas) == "hello"
        assert finish == "stop"

    @pytest.mark.asyncio
    async def test_tool_call_streaming_accumulates_arguments(self):
        lines: list[str] = []
        lines += _event("response.created", {"type": "response.created", "response": {"id": "r1"}})
        lines += _event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "function_call", "id": "fc", "call_id": "call_1", "name": "get_weather"},
            },
        )
        lines += _event(
            "response.function_call_arguments.delta",
            {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"city":'},
        )
        lines += _event(
            "response.function_call_arguments.delta",
            {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '"SF"}'},
        )
        lines += _event(
            "response.completed",
            {"type": "response.completed", "response": {"id": "r1"}},
        )
        fake = _FakeStreamResponse(lines)
        adapter = _ResponsesStreamAdapter(fake, model="gpt-5")

        seen_name: str = ""
        args_parts: list[str] = []
        finish: str | None = None
        async for chunk in adapter:
            if chunk.choices and chunk.choices[0].delta.tool_calls:
                for tc in chunk.choices[0].delta.tool_calls:
                    if tc.function.name:
                        seen_name = tc.function.name
                    if tc.function.arguments:
                        args_parts.append(tc.function.arguments)
            if chunk.choices and chunk.choices[0].finish_reason:
                finish = chunk.choices[0].finish_reason
        assert seen_name == "get_weather"
        assert json.loads("".join(args_parts)) == {"city": "SF"}
        assert finish == "tool_calls"


# ---------------------------------------------------------------------------
# Adapter header wiring
# ---------------------------------------------------------------------------


class TestAdapterHeaders:
    @pytest.mark.asyncio
    async def test_missing_access_token_raises_auth_error(self):
        async def tokens():
            return {"access_token": "", "account_id": ""}

        adapter = OpenAIResponsesAdapter(tokens_source=tokens)
        with pytest.raises(openai.AuthenticationError):
            adapter._build_headers({"access_token": "", "account_id": ""})
        await adapter.aclose()

    @pytest.mark.asyncio
    async def test_headers_include_required_codex_fields(self):
        async def tokens():
            return {"access_token": "tok", "account_id": "acct_123"}

        adapter = OpenAIResponsesAdapter(tokens_source=tokens)
        headers = adapter._build_headers({"access_token": "tok", "account_id": "acct_123"})
        assert headers["Authorization"] == "Bearer tok"
        assert headers["chatgpt-account-id"] == "acct_123"
        assert "responses=experimental" in headers["OpenAI-Beta"]
        assert headers["originator"] == "codex_cli_rs"
        await adapter.aclose()
