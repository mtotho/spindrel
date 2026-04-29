"""Tests for the OpenAI Responses API adapter (chat.completions → /responses)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from app.services.openai_responses_adapter import (
    OpenAIResponsesAdapter,
    _MODELS_REJECTING_MAX_OUTPUT_TOKENS,
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

    def test_oversize_tool_call_id_is_normalized_consistently(self):
        # Regression: history carrying a tool_call_id from another provider
        # (LiteLLM/Gemini emit long opaque ids) used to blow up the Codex
        # endpoint with "string too long. Expected max length 64". Both the
        # function_call and function_call_output legs must normalize to the
        # same deterministic short form so the pair still matches.
        oversize = "call_" + ("a" * 700)
        _, items = _translate_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": oversize,
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": oversize, "content": "sunny"},
            ]
        )
        fn_call = next(it for it in items if it["type"] == "function_call")
        fn_out = next(it for it in items if it["type"] == "function_call_output")
        assert len(fn_call["call_id"]) <= 64
        assert fn_call["call_id"] != oversize
        assert fn_call["call_id"].startswith("call_")
        assert fn_call["call_id"] == fn_out["call_id"]

    def test_short_tool_call_id_is_passed_through_unchanged(self):
        _, items = _translate_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_abc123", "content": "sunny"},
            ]
        )
        fn_call = next(it for it in items if it["type"] == "function_call")
        fn_out = next(it for it in items if it["type"] == "function_call_output")
        assert fn_call["call_id"] == "call_abc123"
        assert fn_out["call_id"] == "call_abc123"

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

    def test_user_message_with_input_audio_raises_clear_error(self):
        with pytest.raises(ValueError, match="Switch Voice Input Mode to transcribe"):
            _translate_messages(
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": "abc", "format": "wav"},
                            }
                        ],
                    }
                ]
            )


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

    def test_temperature_is_not_forwarded(self):
        body = _build_request_body(
            model="gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            tools=None, tool_choice=None, stream=False,
            extra={"temperature": 0.3, "top_p": 0.8},
        )
        assert "temperature" not in body
        assert body["top_p"] == 0.8

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

    def test_reasoning_summary_defaults_to_auto(self):
        # Without `reasoning.summary` the Codex endpoint omits summary stream
        # events entirely — the UI's thinking display would stay empty. The
        # adapter defaults it so every request opts in.
        body = _build_request_body(
            model="gpt-5", messages=[{"role": "user", "content": "hi"}],
            tools=None, tool_choice=None, stream=True, extra={},
        )
        assert body["reasoning"]["summary"] == "auto"

    def test_caller_reasoning_config_wins_but_summary_still_filled(self):
        body = _build_request_body(
            model="gpt-5", messages=[{"role": "user", "content": "hi"}],
            tools=None, tool_choice=None, stream=True,
            extra={"reasoning": {"effort": "high"}},
        )
        assert body["reasoning"]["effort"] == "high"
        assert body["reasoning"]["summary"] == "auto"

    def test_caller_reasoning_summary_override(self):
        body = _build_request_body(
            model="gpt-5", messages=[{"role": "user", "content": "hi"}],
            tools=None, tool_choice=None, stream=True,
            extra={"reasoning": {"summary": "detailed"}},
        )
        assert body["reasoning"]["summary"] == "detailed"


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

    def test_reasoning_summary_surfaces_as_reasoning_content(self):
        resp = {
            "id": "r", "model": "gpt-5", "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    "summary": [
                        {"type": "summary_text", "text": "First I considered X."},
                        {"type": "summary_text", "text": "Then I settled on Y."},
                    ],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Answer"}],
                },
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        comp = _response_to_completion(resp)
        assert comp.choices[0].message.content == "Answer"
        assert comp.choices[0].message.reasoning_content == (
            "First I considered X.\n\nThen I settled on Y."
        )


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
    async def test_reasoning_summary_deltas_become_reasoning_content(self):
        # Codex streams reasoning summaries when the request sets
        # `reasoning.summary=auto`. StreamAccumulator picks `reasoning_content`
        # off the delta and converts it into `thinking` events — this test
        # pins the adapter's side of that contract, plus the part-boundary
        # separator so multi-part summaries don't jam together.
        lines: list[str] = []
        lines += _event("response.created", {"type": "response.created", "response": {"id": "r1"}})
        lines += _event(
            "response.reasoning_summary_part.added",
            {"type": "response.reasoning_summary_part.added", "part": {}},
        )
        lines += _event(
            "response.reasoning_summary_text.delta",
            {"type": "response.reasoning_summary_text.delta", "delta": "thinking..."},
        )
        lines += _event(
            "response.reasoning_summary_part.added",
            {"type": "response.reasoning_summary_part.added", "part": {}},
        )
        lines += _event(
            "response.reasoning_summary_text.delta",
            {"type": "response.reasoning_summary_text.delta", "delta": "next idea"},
        )
        lines += _event(
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "answer"},
        )
        lines += _event(
            "response.completed",
            {"type": "response.completed", "response": {"id": "r1"}},
        )
        fake = _FakeStreamResponse(lines)
        adapter = _ResponsesStreamAdapter(fake, model="gpt-5")

        reasoning_parts: list[str] = []
        content_parts: list[str] = []
        async for chunk in adapter:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)
            if delta.content:
                content_parts.append(delta.content)
        assert "".join(content_parts) == "answer"
        assert "".join(reasoning_parts) == "thinking...\n\nnext idea"

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

    @pytest.mark.asyncio
    async def test_tool_call_finalized_via_output_item_done_when_deltas_absent(self):
        """Regression: gpt-5-codex fast-path emits function_call items whose
        arguments arrive only in ``output_item.done``, not as ``.delta`` events.
        Without finalization handling we'd emit an empty-args tool call and the
        downstream loop would skip the tool invocation entirely — the exact
        class of bug that caused sag-bot to narrate fake skill-review results.
        """
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
        # NO .delta events — the model emits the full args in output_item.done.
        lines += _event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc",
                    "call_id": "call_1",
                    "name": "get_weather",
                    "arguments": '{"city":"SF"}',
                },
            },
        )
        lines += _event(
            "response.completed",
            {"type": "response.completed", "response": {"id": "r1"}},
        )
        fake = _FakeStreamResponse(lines)
        adapter = _ResponsesStreamAdapter(fake, model="gpt-5-codex")

        args_parts: list[str] = []
        seen_name: str = ""
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
        # The finalized args must survive the missing delta stream.
        assert json.loads("".join(args_parts)) == {"city": "SF"}
        assert finish == "tool_calls"

    @pytest.mark.asyncio
    async def test_output_item_done_skips_already_streamed_args(self):
        """If the deltas already accumulated the full arg string, the done
        event should be a no-op — emitting the tail again would double-count.
        """
        lines: list[str] = []
        lines += _event("response.created", {"type": "response.created", "response": {"id": "r1"}})
        lines += _event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "function_call", "id": "fc", "call_id": "c", "name": "f"},
            },
        )
        lines += _event(
            "response.function_call_arguments.delta",
            {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"a":1}'},
        )
        lines += _event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {"type": "function_call", "call_id": "c", "name": "f", "arguments": '{"a":1}'},
            },
        )
        lines += _event("response.completed", {"type": "response.completed", "response": {"id": "r1"}})
        fake = _FakeStreamResponse(lines)
        adapter = _ResponsesStreamAdapter(fake, model="gpt-5")

        args_parts: list[str] = []
        async for chunk in adapter:
            if chunk.choices and chunk.choices[0].delta.tool_calls:
                for tc in chunk.choices[0].delta.tool_calls:
                    if tc.function.arguments:
                        args_parts.append(tc.function.arguments)
        assert "".join(args_parts) == '{"a":1}'

    @pytest.mark.asyncio
    async def test_response_incomplete_maps_to_length(self):
        """response.incomplete with max_output_tokens must surface as
        finish_reason='length' so llm.py's truncation handling fires."""
        lines: list[str] = []
        lines += _event("response.created", {"type": "response.created", "response": {"id": "r1"}})
        lines += _event(
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "partial"},
        )
        lines += _event(
            "response.incomplete",
            {
                "type": "response.incomplete",
                "response": {
                    "id": "r1",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
        )
        fake = _FakeStreamResponse(lines)
        adapter = _ResponsesStreamAdapter(fake, model="gpt-5")

        finish: str | None = None
        async for chunk in adapter:
            if chunk.choices and chunk.choices[0].finish_reason:
                finish = chunk.choices[0].finish_reason
        assert finish == "length"


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

    @pytest.mark.asyncio
    async def test_retries_without_max_output_tokens_when_codex_rejects_it(self):
        _MODELS_REJECTING_MAX_OUTPUT_TOKENS.clear()

        async def tokens():
            return {"access_token": "tok", "account_id": "acct_123"}

        bad_request = openai.BadRequestError(
            message='Responses API returned 400: {"detail": "Unsupported parameter: max_output_tokens"}',
            response=httpx.Response(
                400,
                request=httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses"),
            ),
            body={"detail": "Unsupported parameter: max_output_tokens"},
        )
        retry_stream = object()
        adapter = OpenAIResponsesAdapter(tokens_source=tokens)

        with patch(
            "app.services.openai_responses_adapter._ResponsesStreamAdapter.create",
            new=AsyncMock(side_effect=[bad_request, retry_stream]),
        ) as create:
            result = await adapter.chat.completions.create(
                model="gpt-5.3-codex-spark",
                messages=[{"role": "user", "content": "summarize"}],
                stream=True,
                max_tokens=256,
            )

        assert result is retry_stream
        assert create.await_count == 2
        first_body = create.await_args_list[0].args[3]
        retry_body = create.await_args_list[1].args[3]
        assert first_body["max_output_tokens"] == 256
        assert "max_output_tokens" not in retry_body
        assert (
            "https://chatgpt.com/backend-api/codex",
            "gpt-5.3-codex-spark",
        ) in _MODELS_REJECTING_MAX_OUTPUT_TOKENS
        await adapter.aclose()

    @pytest.mark.asyncio
    async def test_omits_max_output_tokens_after_model_rejection_is_cached(self):
        _MODELS_REJECTING_MAX_OUTPUT_TOKENS.clear()
        _MODELS_REJECTING_MAX_OUTPUT_TOKENS.add((
            "https://chatgpt.com/backend-api/codex",
            "gpt-5.3-codex-spark",
        ))

        async def tokens():
            return {"access_token": "tok", "account_id": "acct_123"}

        retry_stream = object()
        adapter = OpenAIResponsesAdapter(tokens_source=tokens)

        with patch(
            "app.services.openai_responses_adapter._ResponsesStreamAdapter.create",
            new=AsyncMock(return_value=retry_stream),
        ) as create:
            result = await adapter.chat.completions.create(
                model="gpt-5.3-codex-spark",
                messages=[{"role": "user", "content": "summarize"}],
                stream=True,
                max_tokens=256,
            )

        assert result is retry_stream
        assert create.await_count == 1
        body = create.await_args.args[3]
        assert "max_output_tokens" not in body
        await adapter.aclose()
        _MODELS_REJECTING_MAX_OUTPUT_TOKENS.clear()
