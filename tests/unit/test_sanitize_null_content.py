"""Tests for null/missing content sanitization."""

from unittest.mock import MagicMock

from app.agent.loop import _sanitize_messages


class TestSanitizeMessages:
    """_sanitize_messages ensures every message dict has a non-null content field."""

    def test_assistant_no_tool_calls_null_content(self):
        msgs = [{"role": "assistant", "content": None}]
        result = _sanitize_messages(msgs)
        assert result[0]["content"] == ""

    def test_user_null_content(self):
        msgs = [{"role": "user", "content": None}]
        result = _sanitize_messages(msgs)
        assert result[0]["content"] == ""

    def test_tool_null_content(self):
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "abc", "type": "function", "function": {"name": "test", "arguments": "{}"}}]},
            {"role": "tool", "content": None, "tool_call_id": "abc"},
        ]
        result = _sanitize_messages(msgs)
        assert result[1]["content"] == ""
        assert result[1]["tool_call_id"] == "abc"

    def test_orphaned_tool_result_removed(self):
        """Tool results with no matching tool_call should be stripped."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "result", "tool_call_id": "orphaned_id"},
            {"role": "assistant", "content": "done"},
        ]
        result = _sanitize_messages(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_missing_content_key(self):
        msgs = [{"role": "assistant"}]
        result = _sanitize_messages(msgs)
        assert result[0]["content"] == ""

    def test_normal_messages_untouched(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "system", "content": "you are helpful"},
        ]
        result = _sanitize_messages(msgs)
        assert result == msgs

    def test_does_not_mutate_original(self):
        original = {"role": "assistant", "content": None}
        msgs = [original]
        result = _sanitize_messages(msgs)
        assert result[0]["content"] == ""
        # Original dict should still have None
        assert original["content"] is None


class TestMessageToDictFallback:
    """_message_to_dict should set content='' when content is None, regardless of tool_calls."""

    def test_null_content_no_tool_calls(self):
        from app.services.sessions import _message_to_dict

        msg = MagicMock()
        msg.role = "assistant"
        msg.content = None
        msg.tool_calls = None
        msg.tool_call_id = None
        msg.metadata_ = None
        msg.attachments = []

        result = _message_to_dict(msg)
        assert result["content"] == ""

    def test_null_content_with_tool_calls(self):
        from app.services.sessions import _message_to_dict

        msg = MagicMock()
        msg.role = "assistant"
        msg.content = None
        msg.tool_calls = [{"id": "1", "type": "function", "function": {"name": "test", "arguments": "{}"}}]
        msg.tool_call_id = None
        msg.metadata_ = None
        msg.attachments = []

        result = _message_to_dict(msg)
        assert result["content"] == ""
        assert result["tool_calls"] == msg.tool_calls

    def test_valid_content_preserved(self):
        from app.services.sessions import _message_to_dict

        msg = MagicMock()
        msg.role = "user"
        msg.content = "hello world"
        msg.tool_calls = None
        msg.tool_call_id = None
        msg.metadata_ = None
        msg.attachments = []

        result = _message_to_dict(msg)
        assert result["content"] == "hello world"
