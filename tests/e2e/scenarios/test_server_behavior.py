"""Tier 2: Server behavior tests — verify server plumbing with any LLM.

These test streaming, tool dispatch, context persistence, and channel isolation.
They should pass with any model that can follow basic instructions. The model
is configured via E2E_DEFAULT_MODEL (default: gemma4:e4b).

Migrated from test_regressions.py to separate LLM-dependent tests from pure API tests.
"""

from __future__ import annotations

import re

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_response(client: E2EClient) -> None:
    """Chat endpoint must return a session_id and non-empty response."""
    cid = client.new_client_id()
    resp = await client.chat("Say the word 'hello'.", client_id=cid)
    assert resp.session_id, "Must return a session_id"
    assert len(resp.response) > 0, "Response must not be empty"


@pytest.mark.asyncio
async def test_stream_returns_events(client: E2EClient) -> None:
    """Stream endpoint must return at least one response event."""
    cid = client.new_client_id()
    result = await client.chat_stream(
        "Say the word 'hello'.", client_id=cid
    )
    assert len(result.events) > 0, "Must return at least one SSE event"
    assert result.response_text, "Must produce response text"
    assert not result.error_events, "Must not produce error events"


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_dispatch_chat(client: E2EClient) -> None:
    """Bot should call a time tool when asked for the current time."""
    cid = client.new_client_id()
    resp = await client.chat(
        "What is the current time right now? Use your time tool.",
        client_id=cid,
    )
    assert re.search(r"\d{1,2}:\d{2}", resp.response), (
        f"Response should contain a time but got: {resp.response[:200]}"
    )


@pytest.mark.asyncio
async def test_tool_dispatch_stream(client: E2EClient) -> None:
    """Streaming should emit tool_start and tool_result events when tools are used."""
    cid = client.new_client_id()
    result = await client.chat_stream(
        "What is the current time right now? Use your time tool.",
        client_id=cid,
    )
    assert result.response_text, "Must produce response text"
    assert not result.error_events, "Must not produce error events"

    assert len(result.tool_events) > 0, (
        f"Should have tool events but got types: {result.event_types}"
    )
    assert any(e.type == "tool_start" for e in result.tool_events), (
        "Should have a tool_start event"
    )
    assert any(e.type == "tool_result" for e in result.tool_events), (
        "Should have a tool_result event"
    )

    time_tools = {"get_current_time", "get_current_local_time"}
    assert any(t in time_tools for t in result.tools_used), (
        f"Should have used a time tool but used: {result.tools_used}"
    )


# ---------------------------------------------------------------------------
# Multi-turn context persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_turn_context(client: E2EClient) -> None:
    """Second message in same channel should have context from first."""
    cid = client.new_client_id()

    await client.chat(
        "The secret code is PINEAPPLE42. Acknowledge you received it.",
        client_id=cid,
    )

    resp = await client.chat(
        "What was the secret code from my previous message?",
        client_id=cid,
    )
    assert "PINEAPPLE42" in resp.response.upper().replace(" ", ""), (
        "Bot should recall context from previous turn"
    )


# ---------------------------------------------------------------------------
# Channel isolation
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Tool depth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_result_in_response(client: E2EClient) -> None:
    """Tool result should be incorporated into the final response text."""
    cid = client.new_client_id()
    result = await client.chat_stream(
        "Use your time tool to get the current time, then tell me the time "
        "in your response. You MUST include the exact time.",
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert len(result.tool_events) > 0, "Should have tool events"

    time_tools = {"get_current_time", "get_current_local_time"}
    assert any(t in time_tools for t in result.tools_used), (
        f"Should have used a time tool but used: {result.tools_used}"
    )
    assert re.search(r"\d{1,2}:\d{2}", result.response_text), (
        f"Response should contain a time: {result.response_text[:200]}"
    )


@pytest.mark.asyncio
async def test_no_tool_when_unnecessary(client: E2EClient) -> None:
    """Bot should NOT call action tools for a simple factual question.

    Memory-scheme tools (search_memory, get_memory_file) may fire
    proactively and are excluded from this check.
    """
    cid = client.new_client_id()
    result = await client.chat_stream(
        "What is 2 + 2? Just answer with the number.",
        client_id=cid,
    )
    assert not result.error_events, f"Errors: {result.error_events}"
    assert result.response_text, "Should have a response"
    _memory_tools = {"search_memory", "get_memory_file"}
    _action_tools = [t for t in result.tools_used if t not in _memory_tools]
    assert not _action_tools, (
        f"Should not use action tools for simple math, but used: {_action_tools}"
    )


# ---------------------------------------------------------------------------
# Rapid messages (throttle bypass)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_messages_not_throttled(client: E2EClient) -> None:
    """Rapid sequential messages with sender_type=human should not be throttled."""
    cid = client.new_client_id()
    for i in range(3):
        resp = await client.chat(
            f"Throttle test message {i}",
            client_id=cid,
        )
        assert resp.response, f"Message {i} should get a response"
