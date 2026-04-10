"""OpenAI native provider smoke tests — runs against the real OpenAI API.

These tests exercise the OpenAIDriver path (app/services/provider_drivers/openai_driver.py)
directly, NOT through litellm. They are intentionally separate from test_model_smoke.py
because:

1. They are pinned to a specific provider_id ("openai") rather than relying on
   model→provider auto-resolution.
2. They assert OpenAI-specific streaming + tool-call behavior that the generic
   parametrized smoke tests don't cover, including the regression class for the
   tool-call name concatenation bug fixed in session 2026-04-10-8 (where Gemini's
   OpenAI-compat endpoint sent the full name in every delta and `+=` corrupted it).

Cost: ~$0.001-0.005 per full file run on gpt-5-nano. Skips cleanly if the
"openai" provider is not configured on the target instance.
"""

from __future__ import annotations

import re

import pytest

from ..harness.client import E2EClient

OPENAI_PROVIDER_ID = "openai"
OPENAI_MODEL = "gpt-5-nano"


@pytest.fixture
async def openai_bot(client: E2EClient):
    """Temporary bot pinned to gpt-5-nano on the real OpenAI provider.

    Skips the test if the openai provider is not registered on this instance —
    register it via POST /api/v1/admin/providers to enable these tests.
    """
    resp = await client.get(f"/api/v1/admin/providers/{OPENAI_PROVIDER_ID}")
    if resp.status_code == 404:
        pytest.skip(f"Provider '{OPENAI_PROVIDER_ID}' not configured on this instance")
    resp.raise_for_status()

    bot_id = await client.create_temp_bot(
        model=OPENAI_MODEL,
        provider_id=OPENAI_PROVIDER_ID,
        tools=["get_current_time"],
        system_prompt="You are a test bot. Reply tersely. Follow instructions exactly.",
    )
    yield bot_id
    await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_chat(client: E2EClient, openai_bot: str) -> None:
    """Non-streaming chat round-trip via OpenAIDriver.

    Validates: provider lookup, API key decryption, AsyncOpenAI client construction,
    /v1/chat/completions request shape, response parsing, session creation.
    """
    cid = client.new_client_id("openai-smoke-basic")
    resp = await client.chat(
        "Reply with exactly: ok",
        bot_id=openai_bot,
        client_id=cid,
    )
    assert resp.session_id, "Expected a session_id from /chat"
    assert resp.response, "Expected non-empty response"
    assert "ok" in resp.response.lower(), (
        f"Expected 'ok' in response, got: {resp.response[:200]}"
    )


@pytest.mark.asyncio
async def test_streaming_deltas(client: E2EClient, openai_bot: str) -> None:
    """Streaming chat assembles many small text_delta events into the final text.

    Regression coverage for the tool-name concat bug class (session 2026-04-10-8):
    OpenAI streams content as many small deltas. If the StreamAccumulator ever
    breaks delta accumulation, multi-token responses fragment or duplicate.
    """
    cid = client.new_client_id("openai-smoke-stream")
    result = await client.chat_stream(
        "Count from one to five separated by commas. Reply with only the digits.",
        bot_id=openai_bot,
        client_id=cid,
    )
    assert not result.error_events, (
        f"Stream produced error events: {[e.data for e in result.error_events]}"
    )
    assert result.response_text, "Stream produced no response_text"

    text_deltas = [e for e in result.events if e.type == "text_delta"]
    assert len(text_deltas) >= 5, (
        f"Expected multiple text_delta events from OpenAI streaming, got {len(text_deltas)}"
    )

    for digit in ("1", "2", "3", "4", "5"):
        assert digit in result.response_text, (
            f"Expected '{digit}' in streamed response, got: {result.response_text[:200]}"
        )


@pytest.mark.asyncio
async def test_tool_call(client: E2EClient, openai_bot: str) -> None:
    """Single-tool dispatch and post-tool resumption.

    Validates: tool schema serialization for OpenAI, tool_call_id round-trip,
    the agent loop resuming generation after the tool result is appended. The
    "done" suffix catches the failure mode where the model's post-tool turn
    returns empty (seen with Flash Lite after sub-agent results — would be
    devastating to ship for OpenAI silently).
    """
    cid = client.new_client_id("openai-smoke-tool")
    resp = await client.chat(
        "Call your time tool to get the current time. After you have the result, "
        "tell me the time and then write the word done on its own line.",
        bot_id=openai_bot,
        client_id=cid,
    )
    assert resp.response, "Expected non-empty response after tool call"
    assert re.search(r"\d{1,2}:\d{2}", resp.response), (
        f"Expected HH:MM time pattern in response, got: {resp.response[:300]}"
    )
    assert "done" in resp.response.lower(), (
        f"Expected 'done' (post-tool resumption marker) in response, got: {resp.response[:300]}"
    )


@pytest.mark.asyncio
async def test_streaming_with_tool_call(client: E2EClient, openai_bot: str) -> None:
    """Streaming + tool call — the exact pattern that broke in session 2026-04-10-8.

    The session-8 bug was: streaming tool-call name accumulated across deltas
    (`tc["function"]["name"] += delta.function.name`). For Gemini's compat endpoint
    that sends the name in every chunk, this produced "get_current_timeget_current_time...".
    OpenAI sends the name only in the first delta, but ANY regression in the
    accumulator logic surfaces here as either a 4xx/5xx from the provider or
    an error_event in the stream.
    """
    cid = client.new_client_id("openai-smoke-stream-tool")
    result = await client.chat_stream(
        "Call your time tool to get the current time, then state the time you received.",
        bot_id=openai_bot,
        client_id=cid,
    )
    assert not result.error_events, (
        f"Streaming tool call produced error events: "
        f"{[e.data for e in result.error_events]}"
    )
    assert result.response_text, "Streaming tool call produced no response_text"
    assert re.search(r"\d{1,2}:\d{2}", result.response_text), (
        f"Expected HH:MM in streamed response, got: {result.response_text[:300]}"
    )
