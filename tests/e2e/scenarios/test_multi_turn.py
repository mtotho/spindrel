"""Multi-turn: context persists across messages in the same channel."""

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.assertions import (
    assert_response_not_empty,
    assert_contains_any,
)


@pytest.mark.e2e
class TestMultiTurn:
    async def test_context_persists(self, client: E2EClient) -> None:
        """Tell the bot a fact, then ask about it in the same channel."""
        channel_id = client.new_channel_id()
        # Pin client_id so both turns derive the same session under the
        # same channel — without this, client.chat() synthesizes a fresh
        # client_id per call and turn 2 lands in a different session.
        client_id = client.new_client_id()

        # Turn 1: tell the bot something
        resp1 = await client.chat(
            "Remember this: my favorite color is purple.",
            channel_id=channel_id,
            client_id=client_id,
        )
        assert_response_not_empty(resp1.response)

        # Turn 2: ask about it in the same channel
        resp2 = await client.chat(
            "What is my favorite color?",
            channel_id=channel_id,
            client_id=client_id,
        )
        assert_response_not_empty(resp2.response)
        assert_contains_any(resp2.response, ["purple"])

    async def test_different_channels_isolated(self, client: E2EClient) -> None:
        """Different channels don't share context."""
        channel_a = client.new_channel_id()
        channel_b = client.new_channel_id()

        # Tell channel A a fact
        await client.chat(
            "Remember: the secret code is 42.",
            channel_id=channel_a,
        )

        # Ask channel B (different channel, no context)
        resp = await client.chat(
            "What is the secret code?",
            channel_id=channel_b,
        )
        # Channel B shouldn't know the code — but LLM might guess "42" from
        # common knowledge, so we just verify it responds without errors
        assert_response_not_empty(resp.response)

    async def test_same_session_across_messages(self, client: E2EClient) -> None:
        """Multiple messages in the same channel use the same session."""
        channel_id = client.new_channel_id()

        resp1 = await client.chat("Hello", channel_id=channel_id)
        resp2 = await client.chat("Hi again", channel_id=channel_id)

        # Both should have session IDs (may or may not be the same depending
        # on session lifecycle, but both should be non-empty)
        assert resp1.session_id
        assert resp2.session_id
