"""Priority 3 tests for app.services.compaction — message filtering, summary generation."""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.compaction import (
    _compaction_metadata,
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

    def test_heartbeat_messages_excluded(self):
        """Heartbeat messages must never leak into summaries or section files."""
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "hb prompt", "_metadata": {"is_heartbeat": True}},
            {"role": "assistant", "content": "hb response", "_metadata": {"is_heartbeat": True}},
            {"role": "user", "content": "real question"},
            {"role": "assistant", "content": "real answer"},
        ]
        result = _messages_for_summary(messages)
        contents = [m["content"] for m in result]
        assert "hb prompt" not in contents
        assert "hb response" not in contents
        assert "hi" in contents
        assert "hello" in contents
        assert "real question" in contents
        assert "real answer" in contents
        assert len(result) == 4

    def test_only_heartbeats_returns_empty(self):
        """If all messages are heartbeats, result should be empty."""
        messages = [
            {"role": "user", "content": "hb1", "_metadata": {"is_heartbeat": True}},
            {"role": "assistant", "content": "r1", "_metadata": {"is_heartbeat": True}},
            {"role": "user", "content": "hb2", "_metadata": {"is_heartbeat": True}},
            {"role": "assistant", "content": "r2", "_metadata": {"is_heartbeat": True}},
        ]
        result = _messages_for_summary(messages)
        assert result == []

    def test_heartbeat_tool_messages_excluded(self):
        """Heartbeat exchanges that include tool calls are also filtered."""
        messages = [
            {"role": "user", "content": "real msg"},
            {"role": "user", "content": "hb prompt", "_metadata": {"is_heartbeat": True}},
            {"role": "assistant", "content": "hb thinking", "_metadata": {"is_heartbeat": True}},
            {"role": "tool", "content": "tool output", "_metadata": {"is_heartbeat": True}},
            {"role": "assistant", "content": "hb final", "_metadata": {"is_heartbeat": True}},
            {"role": "assistant", "content": "real reply"},
        ]
        result = _messages_for_summary(messages)
        contents = [m["content"] for m in result]
        assert "hb prompt" not in contents
        assert "hb thinking" not in contents
        assert "tool output" not in contents
        assert "hb final" not in contents
        assert "real msg" in contents
        assert "real reply" in contents

    def test_compaction_run_messages_excluded(self):
        messages = [
            {"role": "user", "content": "real question"},
            {
                "role": "assistant",
                "content": "",
                "_metadata": {"kind": "compaction_run", "source": "compaction"},
            },
            {"role": "assistant", "content": "real answer"},
        ]
        result = _messages_for_summary(messages)
        assert [m["content"] for m in result] == ["real question", "real answer"]


class TestCompactionRunMetadata:
    def test_metadata_is_visible_but_not_replayable(self):
        bot = SimpleNamespace(id="test-bot", name="Test Bot")
        metadata = _compaction_metadata(
            bot=bot,
            origin="manual",
            status="queued",
            detail="A response is still running.",
        )

        assert metadata["kind"] == "compaction_run"
        assert metadata["source"] == "compaction"
        assert metadata["compaction_origin"] == "manual"
        assert metadata["compaction_status"] == "queued"
        assert metadata["assistant_turn_body"] == {"version": 1, "items": []}
        assert metadata["envelope"]["content_type"] == "text/markdown"
        assert metadata["envelope"]["display"] == "panel"
        assert metadata["envelope"]["view_key"] == "compaction_run"
        assert "hidden" not in metadata
        assert "pipeline_step" not in metadata
