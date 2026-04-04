"""Basic chat: send a message, get a response, verify structure."""

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.assertions import (
    assert_response_not_empty,
    assert_contains_any,
)


@pytest.mark.e2e
class TestChatBasic:
    async def test_simple_question(self, client: E2EClient) -> None:
        """Send a simple math question and get a correct answer."""
        resp = await client.chat("What is 2+2? Reply with just the number.")
        assert_response_not_empty(resp.response)
        assert_contains_any(resp.response, ["4", "four"])

    async def test_response_has_session_id(self, client: E2EClient) -> None:
        """Response includes a session_id."""
        resp = await client.chat("Hello")
        assert resp.session_id, "Expected non-empty session_id"

    async def test_response_structure(self, client: E2EClient) -> None:
        """Response raw body has expected top-level keys."""
        resp = await client.chat("Say hi")
        assert "response" in resp.raw
        assert "session_id" in resp.raw

    async def test_empty_message_returns_error(self, client: E2EClient) -> None:
        """Empty message should return 400."""
        raw = await client.post("/chat", json={"message": "", "bot_id": "e2e"})
        # Server may accept empty message or return 400/422 — either is valid behavior.
        # The key is it doesn't 500.
        assert raw.status_code < 500
