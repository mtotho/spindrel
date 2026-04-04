"""Tool usage: prompt that triggers tool calls, verify tool events in stream."""

import re

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.assertions import (
    assert_response_not_empty,
    assert_contains_any,
    assert_no_error_events,
)


@pytest.mark.e2e
class TestToolUsage:
    async def test_time_tool_via_stream(self, client: E2EClient) -> None:
        """Ask for the time — LLM should use get_current_local_time or get_current_time."""
        result = await client.chat_stream(
            "What time is it right now? Use your tools to find out."
        )
        assert_no_error_events(result.events)
        assert_response_not_empty(result.response_text)

        # The bot should have called one of the time tools
        assert result.tools_used, (
            f"Expected tool usage, got none. Events: {result.event_types}"
        )
        assert_contains_any(
            " ".join(result.tools_used),
            ["get_current_local_time", "get_current_time"],
        )

    async def test_time_tool_via_chat(self, client: E2EClient) -> None:
        """Non-streaming: ask for time, verify response has time-like content."""
        resp = await client.chat(
            "What is the current time? Use your tools."
        )
        assert_response_not_empty(resp.response)
        # Response should contain time-like patterns (digits, colon, AM/PM, etc.)
        assert re.search(r"\d{1,2}[:\-]\d{2}", resp.response), (
            f"Expected time-like pattern in response: {resp.response[:200]}"
        )

    async def test_tool_events_have_data(self, client: E2EClient) -> None:
        """Tool events in the stream contain meaningful data."""
        result = await client.chat_stream(
            "Please tell me the current UTC time using your tools."
        )
        tool_events = result.tool_events
        if tool_events:
            for event in tool_events:
                # Tool events should have some identifying data
                assert event.data, f"Tool event has empty data: {event}"
