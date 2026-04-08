"""Regression tests for specific bugs that were found and fixed.

Each test documents the bug it catches and the fix that resolved it.
These run against the live server in external mode.
"""

from __future__ import annotations

import re
import uuid

import pytest

from ..harness.client import E2EClient

_TEST_PREFIX = "e2e-regr-"


def _test_bot_id() -> str:
    return f"{_TEST_PREFIX}{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Bug: BotUpdateIn missing carapaces field (April 8, 2026)
# Fix: Added carapaces: Optional[list[str]] to BotUpdateIn
# File: app/routers/api_v1_admin/_schemas.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_carapaces_update_not_dropped(client: E2EClient) -> None:
    """PATCH bot with carapaces must persist the value, not silently drop it."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Regr carapaces", "model": "gemini/gemini-2.5-flash"}
        )

        # This was the exact operation that failed — UI sends carapaces via PATCH
        result = await client.update_bot(bot_id, {"carapaces": ["orchestrator"]})
        assert result["carapaces"] == ["orchestrator"], (
            "PATCH must accept and return carapaces"
        )

        # And it must persist, not just echo back
        fetched = await client.get_bot(bot_id)
        assert fetched["carapaces"] == ["orchestrator"], (
            "Carapaces must persist after PATCH"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Bug: BotOut missing carapaces field (April 8, 2026)
# Fix: Added carapaces: list[str] = [] to BotOut
# File: app/routers/api_v1_admin/_schemas.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_bot_out_has_carapaces(client: E2EClient) -> None:
    """GET /bots/{id} must include carapaces in the response body."""
    bot_id = _test_bot_id()
    try:
        created = await client.create_bot(
            {"id": bot_id, "name": "Regr BotOut", "model": "gemini/gemini-2.5-flash"}
        )
        assert "carapaces" in created, "BotOut must include carapaces field"
        assert isinstance(created["carapaces"], list)
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Bug: Updating unrelated fields wipes carapaces (potential regression)
# This tests that PATCH with partial fields doesn't null out other fields.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_partial_update_preserves_carapaces(
    client: E2EClient,
) -> None:
    """Updating bot name must not clear carapaces."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Partial", "model": "gemini/gemini-2.5-flash"}
        )
        await client.update_bot(bot_id, {"carapaces": ["e2e-testing"]})

        # Update an unrelated field
        result = await client.update_bot(bot_id, {"name": "Partial Updated"})
        assert result["carapaces"] == ["e2e-testing"], (
            "Unrelated PATCH must not wipe carapaces"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Bug: Channel throttle blocks rapid API requests (April 8, 2026)
# Fix: E2E client sends sender_type: "human" in msg_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_rapid_api_messages_not_throttled(
    client: E2EClient,
) -> None:
    """Rapid sequential messages with sender_type=human should not be throttled."""
    cid = client.new_client_id()
    # Send 3 messages in quick succession — previously this would hit throttle
    for i in range(3):
        resp = await client.chat(
            f"Throttle test message {i}",
            client_id=cid,
        )
        assert resp.response, f"Message {i} should get a response"


# ---------------------------------------------------------------------------
# Bug: Bot creation defaults (convention enforcement)
# memory_scheme should default to "workspace-files", not null
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_bot_default_memory_scheme(client: E2EClient) -> None:
    """New bots must default to memory_scheme='workspace-files'."""
    bot_id = _test_bot_id()
    try:
        created = await client.create_bot(
            {"id": bot_id, "name": "Defaults", "model": "gemini/gemini-2.5-flash"}
        )
        assert created.get("memory_scheme") == "workspace-files", (
            "memory_scheme must default to 'workspace-files'"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Chat regression: basic round-trip still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_chat_returns_valid_session(client: E2EClient) -> None:
    """Chat endpoint must return a session_id and non-empty response."""
    cid = client.new_client_id()
    resp = await client.chat("Say the word 'hello'.", client_id=cid)
    assert resp.session_id, "Must return a session_id"
    assert len(resp.response) > 0, "Response must not be empty"


@pytest.mark.asyncio
async def test_regression_stream_returns_events(client: E2EClient) -> None:
    """Stream endpoint must return at least one response event."""
    cid = client.new_client_id()
    result = await client.chat_stream(
        "Say the word 'hello'.", client_id=cid
    )
    assert len(result.events) > 0, "Must return at least one SSE event"
    assert result.response_text, "Must produce response text"
    assert not result.error_events, "Must not produce error events"


# ---------------------------------------------------------------------------
# Multi-turn context persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_multi_turn_context(client: E2EClient) -> None:
    """Second message in same channel should have context from first."""
    cid = client.new_client_id()

    # First turn: establish a fact (avoid "remember" — triggers memory tool seeking)
    await client.chat(
        "The secret code is PINEAPPLE42. Acknowledge you received it.",
        client_id=cid,
    )

    # Second turn: ask about it (same client_id = same channel + session)
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
# Tool calling: bot should use tools when appropriate
# The e2e bot has get_current_time and get_current_local_time tools.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_tool_calling_chat(client: E2EClient) -> None:
    """Bot should call a time tool when asked for the current time."""
    cid = client.new_client_id()
    resp = await client.chat(
        "What is the current time right now? Use your time tool.",
        client_id=cid,
    )
    # The response should contain time-like content (digits with colons)
    assert re.search(r"\d{1,2}:\d{2}", resp.response), (
        f"Response should contain a time but got: {resp.response[:200]}"
    )


@pytest.mark.asyncio
async def test_regression_tool_calling_stream(client: E2EClient) -> None:
    """Streaming should emit tool_start and tool_result events when tools are used."""
    cid = client.new_client_id()
    result = await client.chat_stream(
        "What is the current time right now? Use your time tool.",
        client_id=cid,
    )
    assert result.response_text, "Must produce response text"
    assert not result.error_events, "Must not produce error events"

    # Verify tool events were emitted
    assert len(result.tool_events) > 0, (
        f"Should have tool events but got types: {result.event_types}"
    )
    assert any(e.type == "tool_start" for e in result.tool_events), (
        "Should have a tool_start event"
    )
    assert any(e.type == "tool_result" for e in result.tool_events), (
        "Should have a tool_result event"
    )

    # Verify the tool used was one of the time tools
    time_tools = {"get_current_time", "get_current_local_time"}
    assert any(t in time_tools for t in result.tools_used), (
        f"Should have used a time tool but used: {result.tools_used}"
    )


# ---------------------------------------------------------------------------
# Tool persistence: bot tools survive PATCH updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_bot_tools_persist_after_update(client: E2EClient) -> None:
    """Updating a bot field must not wipe its local_tools list."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {
                "id": bot_id,
                "name": "Tools persist",
                "model": "gemini/gemini-2.5-flash-lite",
                "local_tools": ["get_current_time"],
            }
        )

        # Update an unrelated field
        result = await client.update_bot(bot_id, {"name": "Tools persist v2"})
        assert "get_current_time" in result.get("local_tools", []), (
            "local_tools must survive unrelated PATCH"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Channel isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_channel_isolation(client: E2EClient) -> None:
    """Messages in one channel must not leak to another."""
    cid_a = client.new_client_id()
    cid_b = client.new_client_id()

    # Establish context in channel A
    await client.chat(
        "The password is ZEBRA99. Acknowledge you received it.",
        client_id=cid_a,
    )

    # Ask in channel B — should NOT know the password
    resp = await client.chat(
        "What password did I tell you in a previous message?",
        client_id=cid_b,
    )
    assert "ZEBRA99" not in resp.response.upper().replace(" ", ""), (
        "Channel B must not see Channel A's context"
    )


# ---------------------------------------------------------------------------
# Capability activation: carapaces can be assigned and removed via API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_capability_activation_roundtrip(
    client: E2EClient,
) -> None:
    """Activating and deactivating a carapace must reflect in bot config."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Cap test", "model": "gemini/gemini-2.5-flash-lite"}
        )

        # Activate
        result = await client.update_bot(bot_id, {"carapaces": ["e2e-testing"]})
        assert result["carapaces"] == ["e2e-testing"], "Carapace must activate"

        # Verify persistence
        fetched = await client.get_bot(bot_id)
        assert fetched["carapaces"] == ["e2e-testing"], "Activation must persist"

        # Deactivate
        result = await client.update_bot(bot_id, {"carapaces": []})
        assert result["carapaces"] == [], "Carapace must deactivate"

        # Verify deactivation persists
        fetched = await client.get_bot(bot_id)
        assert fetched["carapaces"] == [], "Deactivation must persist"
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# Multiple capabilities: bot can have several carapaces at once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_multiple_capabilities(client: E2EClient) -> None:
    """Bot should support multiple carapaces simultaneously."""
    bot_id = _test_bot_id()
    try:
        await client.create_bot(
            {"id": bot_id, "name": "Multi cap", "model": "gemini/gemini-2.5-flash-lite"}
        )

        caps = ["e2e-testing", "researcher"]
        result = await client.update_bot(bot_id, {"carapaces": caps})
        assert sorted(result["carapaces"]) == sorted(caps), (
            "Must support multiple carapaces"
        )
    finally:
        await client.delete_bot(bot_id)
