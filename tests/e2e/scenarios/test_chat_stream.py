"""Streaming chat: SSE event sequence and response extraction."""

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.assertions import (
    assert_response_not_empty,
    assert_no_error_events,
    assert_stream_event_sequence,
)


@pytest.mark.e2e
class TestChatStream:
    async def test_stream_returns_events(self, client: E2EClient) -> None:
        """Streaming endpoint returns at least one event."""
        result = await client.chat_stream("Say hello")
        assert len(result.events) > 0, "Expected at least one stream event"

    async def test_stream_has_response(self, client: E2EClient) -> None:
        """Stream ends with a response containing text."""
        result = await client.chat_stream("What is 1+1?")
        assert_response_not_empty(result.response_text)

    async def test_stream_no_errors(self, client: E2EClient) -> None:
        """Stream has no error events for a normal request."""
        result = await client.chat_stream("Hello, how are you?")
        assert_no_error_events(result.events)

    async def test_stream_event_sequence(self, client: E2EClient) -> None:
        """Stream ends with a response event."""
        result = await client.chat_stream("Say hi")
        # The stream should end with a response event
        assert_stream_event_sequence(result.events, ["response"])

    async def test_stream_has_session_id(self, client: E2EClient) -> None:
        """Stream result captures the session ID."""
        result = await client.chat_stream("Hello")
        assert result.session_id, "Expected session_id in stream result"
