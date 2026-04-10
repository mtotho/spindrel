"""Sub-agent spawning E2E tests.

Verifies the spawn_subagents tool — inline, parallel, ephemeral agent execution:
- Bot spawns a single sub-agent and gets the result inline (not posted to channel)
- Bot spawns multiple sub-agents in parallel, gets all results in one tool response
- Preset resolution (file-scanner gets file tools, summarizer gets none, etc.)
- Model tier applied correctly (sub-agents use cheaper models)
- Depth limit: sub-agents cannot spawn their own sub-agents
- Tool access control: sub-agents only get the tools specified by preset/explicit list
- Custom sub-agent (no preset, explicit tools + system prompt)
- Result truncation respects max_chars

These tests are expected to FAIL until spawn_subagents is implemented.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ..harness.assertions import (
    assert_contains_any,
    assert_no_error_events,
    assert_response_not_empty,
    assert_tool_called,
    assert_tool_called_with_args,
    assert_tool_not_called,
)
from ..harness.client import E2EClient

_LLM_TIMEOUT = 120  # sub-agent tests involve multiple LLM calls


async def _create_subagent_bot(client: E2EClient) -> str:
    """Create a minimal temp bot with spawn_subagents + basic tools."""
    bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
    await client.create_bot({
        "id": bot_id,
        "name": "E2E Sub-Agent Bot",
        "model": "gemini/gemini-2.5-flash-lite",
        "system_prompt": (
            "You are a test bot with access to sub-agents. "
            "When told to spawn sub-agents, use the spawn_subagents tool immediately "
            "with the exact arguments given. Do not explain — just call the tool. "
            "After receiving sub-agent results, summarize what each returned."
        ),
        "local_tools": [
            "spawn_subagents",
            "get_current_time",
        ],
        "tool_retrieval": False,
        "persona": False,
        "context_compaction": False,
    })
    return bot_id


# ---------------------------------------------------------------------------
# 1. Single sub-agent spawn returns result inline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_subagent_returns_inline(client: E2EClient) -> None:
    """Bot spawns one sub-agent with a simple prompt. The result comes back
    as a tool response (not posted to channel) and the bot summarizes it."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-single")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with this single sub-agent: '
                '{"preset": "summarizer", "prompt": "Summarize in one sentence: '
                'The quick brown fox jumps over the lazy dog. This sentence contains '
                'every letter of the English alphabet and is commonly used for testing."}',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])
        assert_response_not_empty(result.response_text, min_chars=10)

        # The bot should relay the sub-agent's summary
        assert_contains_any(result.response_text, [
            "pangram", "alphabet", "every letter", "fox", "quick brown",
        ])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 2. Parallel sub-agent spawn — multiple results collected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_subagents_return_all_results(client: E2EClient) -> None:
    """Bot spawns 3 sub-agents in parallel. All results are returned in the
    single tool response. Bot should reference content from all three."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-parallel")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with these three sub-agents:\n'
                '1. {"preset": "summarizer", "prompt": "What is 2+2? Reply with just the number."}\n'
                '2. {"preset": "summarizer", "prompt": "What color is the sky on a clear day? One word."}\n'
                '3. {"preset": "summarizer", "prompt": "Name the largest planet in our solar system. One word."}\n'
                'After getting results, list all three answers.',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # Bot should relay all three sub-agent answers
        text = result.response_text.lower()
        assert "4" in text, f"Should contain answer '4'. Got: {result.response_text[:300]}"
        assert_contains_any(result.response_text, ["blue", "sky"])
        assert_contains_any(result.response_text, ["jupiter"])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 3. File-scanner preset gets file tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_scanner_preset_has_file_tools(client: E2EClient) -> None:
    """Sub-agent with preset 'file-scanner' should be able to use exec_command
    to run shell commands for file scanning."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-scanner")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with one sub-agent: '
                '{"preset": "file-scanner", "prompt": "Use exec_command to run: '
                'ls /opt/thoth-server/*.md — then list what you found."}',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])
        assert_response_not_empty(result.response_text, min_chars=10)

        # The scanner should have found markdown files in the project root
        assert_contains_any(result.response_text, [
            "readme", "contributing", "security", "license", ".md",
        ])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 4. Model tier is applied (sub-agent uses cheaper model)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_model_tier_applied(client: E2EClient) -> None:
    """Sub-agents with model_tier='fast' should resolve to the configured
    fast-tier model. We verify by checking the tool call arguments include
    the tier, and the sub-agent successfully executes (proving resolution worked)."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-tier")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with: '
                '{"preset": "summarizer", "model_tier": "fast", '
                '"prompt": "Say the word PINEAPPLE and nothing else."}',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # The sub-agent ran successfully (model tier resolved) and returned a result
        assert_contains_any(result.response_text, ["pineapple", "PINEAPPLE"])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 5. Depth limit — sub-agents cannot spawn sub-agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_cannot_spawn_subagents(client: E2EClient) -> None:
    """A sub-agent should NOT have spawn_subagents in its tool set, preventing
    recursive spawning. The parent bot's response should indicate the sub-agent
    couldn't delegate further."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-depth")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with: '
                '{"preset": "summarizer", "prompt": "You must call spawn_subagents '
                'to delegate this work. If you cannot, say CANNOT_DELEGATE."}',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # The sub-agent should have reported it can't delegate
        assert_contains_any(result.response_text, [
            "cannot_delegate", "cannot delegate", "cannot", "no tool",
            "not available", "unable to", "don't have", "do not have",
            "could not", "couldn't",
        ])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 6. Tool access control — summarizer has no tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarizer_has_no_tools(client: E2EClient) -> None:
    """The summarizer preset should have no tools (it just processes text).
    If asked to use a tool, it should be unable to."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-notools")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with: '
                '{"preset": "summarizer", "prompt": "Use the get_current_time tool '
                'and tell me the time. If you have no tools, say NO_TOOLS_AVAILABLE."}',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # Sub-agent couldn't use tools — it should say so
        assert_contains_any(result.response_text, [
            "no_tools_available", "no tools", "don't have", "unable",
            "cannot", "not available",
        ])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 7. Custom sub-agent with explicit tools and system prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_subagent_explicit_tools(client: E2EClient) -> None:
    """A sub-agent with no preset but explicit tools and system_prompt should work.
    This tests the escape hatch for custom sub-agent definitions."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-custom")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with: '
                '{"tools": ["get_current_time"], '
                '"system_prompt": "You are a time-checker bot. Call get_current_time and report it.", '
                '"model_tier": "fast", '
                '"prompt": "What time is it right now? Use the tool."}',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # The sub-agent should have gotten the time via get_current_time
        # and the parent should relay something time-related
        assert_contains_any(result.response_text, [
            "time", ":", "am", "pm", "utc", "2026",
        ])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 8. Invalid preset returns error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_preset_returns_error(client: E2EClient) -> None:
    """Requesting a non-existent preset should return an error in the tool result,
    not crash the server."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-badpreset")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Call the spawn_subagents tool right now with this exact JSON for the agents array: '
                '[{"preset": "nonexistent-preset-xyz", "prompt": "Do something."}]',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        # Should not crash — error returned gracefully
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # Bot should relay the error
        assert_contains_any(result.response_text, [
            "error", "not found", "invalid", "unknown",
            "no preset", "nonexistent", "available",
        ])
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 9. Sub-agent results not posted to channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_results_not_posted_to_channel(client: E2EClient) -> None:
    """Sub-agent results should only appear in the parent's tool response,
    NOT as separate messages in the channel. Verify by checking stream events
    contain no delegation_post events."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-nochannel")
        result = await asyncio.wait_for(
            client.chat_stream(
                'Use spawn_subagents with: '
                '{"preset": "summarizer", "prompt": "Say hello."}',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        assert_no_error_events(result.events)
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # No delegation_post events should appear in the stream
        delegation_posts = [e for e in result.events if e.type == "delegation_post"]
        assert not delegation_posts, (
            f"Sub-agent results should NOT be posted to channel. "
            f"Found {len(delegation_posts)} delegation_post event(s)."
        )

        # Only one response event (the parent's), not multiple
        response_events = [e for e in result.events if e.type == "response"]
        assert len(response_events) == 1, (
            f"Expected exactly 1 response event (parent only), got {len(response_events)}"
        )
    finally:
        await client.delete_bot(bot_id)


# ---------------------------------------------------------------------------
# 10. Rate limit — cannot spawn more than N sub-agents per turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_rate_limit(client: E2EClient) -> None:
    """There should be a per-turn limit on sub-agent spawning to prevent abuse.
    Spawning an excessive number should hit the limit gracefully."""
    bot_id = await _create_subagent_bot(client)
    try:
        client_id = client.new_client_id("e2e-subagent-ratelimit")
        # Ask for 25 sub-agents (should exceed limit)
        agents = [
            f'{{"preset": "summarizer", "prompt": "Say number {i}."}}'
            for i in range(25)
        ]
        agents_str = ", ".join(agents)
        result = await asyncio.wait_for(
            client.chat_stream(
                f'Use spawn_subagents with all of these: [{agents_str}]',
                bot_id=bot_id,
                client_id=client_id,
            ),
            timeout=_LLM_TIMEOUT,
        )
        # Should complete without server error
        assert_tool_called(result.tools_used, ["spawn_subagents"])

        # Response should mention the limit or partial results
        assert_contains_any(result.response_text, [
            "limit", "maximum", "too many", "exceeded", "partial",
            "only", "capped",
        ])
    finally:
        await client.delete_bot(bot_id)
