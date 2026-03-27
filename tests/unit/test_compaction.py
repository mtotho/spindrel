"""Priority 3 tests for app.services.compaction — message filtering, summary generation."""
import pytest
from unittest.mock import MagicMock

from app.services.compaction import (
    _messages_for_summary,
)


# ---------------------------------------------------------------------------
# _messages_for_summary
# ---------------------------------------------------------------------------

class TestMessagesForSummary:
    def test_basic_conversation(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _messages_for_summary(messages)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_passive_messages_become_channel_context(self):
        messages = [
            {"role": "user", "content": "ambient", "_metadata": {"passive": True, "sender_id": "alice"}},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _messages_for_summary(messages)
        # Passive becomes system context block, active remains
        assert result[0]["role"] == "system"
        assert "Channel context" in result[0]["content"]
        assert "alice" in result[0]["content"]
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "hello"

    def test_empty_content_skipped(self):
        messages = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "hi"},
        ]
        result = _messages_for_summary(messages)
        assert len(result) == 1
        assert result[0]["content"] == "hi"

    def test_no_passive_messages(self):
        messages = [
            {"role": "user", "content": "ask"},
            {"role": "assistant", "content": "answer"},
        ]
        result = _messages_for_summary(messages)
        # No system block prepended
        assert all(m["role"] != "system" for m in result)

    def test_tool_messages_excluded(self):
        messages = [
            {"role": "user", "content": "do thing"},
            {"role": "tool", "content": "tool output"},
            {"role": "assistant", "content": "done"},
        ]
        result = _messages_for_summary(messages)
        roles = [m["role"] for m in result]
        assert "tool" not in roles

    def test_system_messages_excluded(self):
        messages = [
            {"role": "system", "content": "You are a bot"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _messages_for_summary(messages)
        roles = [m["role"] for m in result]
        assert "system" not in roles
