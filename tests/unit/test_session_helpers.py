"""Unit tests for pure helpers in app.services.sessions."""
import uuid
from types import SimpleNamespace

from app.services.sessions import (
    _filter_old_heartbeats,
    _message_to_dict,
    derive_integration_session_id,
    is_integration_client_id,
    normalize_stored_content,
)


# ---------------------------------------------------------------------------
# normalize_stored_content
# ---------------------------------------------------------------------------

class TestNormalizeStoredContent:
    def test_plain_string(self):
        assert normalize_stored_content("hello") == "hello"

    def test_none(self):
        assert normalize_stored_content(None) is None

    def test_json_multimodal(self):
        import json
        data = [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {}}]
        result = normalize_stored_content(json.dumps(data))
        assert isinstance(result, list)
        assert result[0]["type"] == "text"

    def test_json_list_of_strings_kept_as_string(self):
        import json
        s = json.dumps(["a", "b"])
        assert normalize_stored_content(s) == s

    def test_malformed_json(self):
        s = "[not valid json"
        assert normalize_stored_content(s) == s

    def test_string_starting_with_bracket(self):
        s = "[some slack message]"
        assert normalize_stored_content(s) == s


# ---------------------------------------------------------------------------
# is_integration_client_id
# ---------------------------------------------------------------------------

class TestIsIntegrationClientId:
    def test_slack_prefix(self):
        assert is_integration_client_id("slack:C12345") is True

    def test_discord_prefix(self):
        assert is_integration_client_id("discord:chan1") is True

    def test_teams_prefix(self):
        assert is_integration_client_id("teams:t1") is True

    def test_regular_id(self):
        assert is_integration_client_id("my-client") is False

    def test_none(self):
        assert is_integration_client_id(None) is False

    def test_empty(self):
        assert is_integration_client_id("") is False


# ---------------------------------------------------------------------------
# derive_integration_session_id
# ---------------------------------------------------------------------------

class TestDeriveIntegrationSessionId:
    def test_deterministic(self):
        a = derive_integration_session_id("slack:C12345")
        b = derive_integration_session_id("slack:C12345")
        assert a == b
        assert isinstance(a, uuid.UUID)

    def test_different_inputs(self):
        a = derive_integration_session_id("slack:C1")
        b = derive_integration_session_id("slack:C2")
        assert a != b


# ---------------------------------------------------------------------------
# _message_to_dict – null content on tool-call messages
# ---------------------------------------------------------------------------

def _fake_message(**kwargs):
    """Create a minimal Message-like object for _message_to_dict."""
    defaults = {
        "role": "assistant",
        "content": None,
        "tool_calls": None,
        "tool_call_id": None,
        "metadata_": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestMessageToDictToolCallContent:
    def test_tool_calls_with_none_content_gets_empty_string(self):
        msg = _fake_message(tool_calls=[{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}])
        d = _message_to_dict(msg)
        assert d["content"] == ""

    def test_tool_calls_with_explicit_content_preserved(self):
        msg = _fake_message(content="thinking...", tool_calls=[{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}])
        d = _message_to_dict(msg)
        assert d["content"] == "thinking..."

    def test_no_tool_calls_none_content_uses_empty_string(self):
        msg = _fake_message(content=None, tool_calls=None)
        d = _message_to_dict(msg)
        # Catch-all: content is always present (empty string fallback)
        assert d["content"] == ""


# ---------------------------------------------------------------------------
# _filter_old_heartbeats
# ---------------------------------------------------------------------------

def _hb(role, content):
    """Shortcut for a heartbeat-tagged message."""
    return {"role": role, "content": content, "_metadata": {"is_heartbeat": True}}

def _msg(role, content):
    """Shortcut for a normal message."""
    return {"role": role, "content": content}


class TestFilterOldHeartbeats:
    def test_no_heartbeat_messages(self):
        msgs = [_msg("user", "hi"), _msg("assistant", "hello")]
        assert _filter_old_heartbeats(msgs) == msgs

    def test_single_heartbeat_kept(self):
        msgs = [
            _msg("user", "hi"),
            _hb("user", "hb prompt"),
            _hb("assistant", "hb response"),
            _msg("user", "next"),
        ]
        result = _filter_old_heartbeats(msgs)
        assert len(result) == 4  # all kept, only one heartbeat exchange

    def test_older_heartbeats_dropped(self):
        msgs = [
            _msg("user", "hi"),
            _hb("user", "hb1 prompt"),
            _hb("assistant", "hb1 response"),
            _msg("user", "something"),
            _hb("user", "hb2 prompt"),
            _hb("assistant", "hb2 response"),
            _msg("user", "latest"),
        ]
        result = _filter_old_heartbeats(msgs)
        contents = [m["content"] for m in result]
        assert "hb1 prompt" not in contents
        assert "hb1 response" not in contents
        assert "hb2 prompt" in contents
        assert "hb2 response" in contents
        assert "hi" in contents
        assert "something" in contents
        assert "latest" in contents

    def test_three_heartbeats_keeps_only_last(self):
        msgs = [
            _hb("user", "hb1"), _hb("assistant", "r1"),
            _hb("user", "hb2"), _hb("assistant", "r2"),
            _hb("user", "hb3"), _hb("assistant", "r3"),
        ]
        result = _filter_old_heartbeats(msgs)
        contents = [m["content"] for m in result]
        assert contents == ["hb3", "r3"]

    def test_interleaved_normal_and_heartbeat(self):
        msgs = [
            _msg("user", "u1"),
            _msg("assistant", "a1"),
            _hb("user", "hb1"), _hb("assistant", "r1"),
            _msg("user", "u2"),
            _msg("assistant", "a2"),
            _hb("user", "hb2"), _hb("assistant", "r2"),
            _msg("user", "u3"),
        ]
        result = _filter_old_heartbeats(msgs)
        contents = [m["content"] for m in result]
        # hb1 dropped, hb2 kept, all normal messages kept
        assert "hb1" not in contents
        assert "r1" not in contents
        assert "hb2" in contents
        assert "r2" in contents
        assert len([c for c in contents if c.startswith("u")]) == 3
        assert len([c for c in contents if c.startswith("a")]) == 2

    def test_heartbeat_with_tool_calls(self):
        """Heartbeat exchanges may include tool call messages."""
        msgs = [
            _hb("user", "hb1"),
            _hb("assistant", "r1"),
            {"role": "tool", "content": "tool out", "_metadata": {"is_heartbeat": True}},
            _hb("assistant", "r1 final"),
            _msg("user", "normal"),
            _hb("user", "hb2"),
            _hb("assistant", "r2"),
        ]
        result = _filter_old_heartbeats(msgs)
        contents = [m["content"] for m in result]
        # All hb1 messages (including tool) dropped
        assert "hb1" not in contents
        assert "r1" not in contents
        assert "tool out" not in contents
        assert "r1 final" not in contents
        # hb2 kept
        assert "hb2" in contents
        assert "r2" in contents
        assert "normal" in contents

    def test_empty_list(self):
        assert _filter_old_heartbeats([]) == []

    def test_only_heartbeat_assistant_no_user(self):
        """Edge case: heartbeat assistant message but no heartbeat user message."""
        msgs = [
            _msg("user", "hi"),
            {"role": "assistant", "content": "hb resp", "_metadata": {"is_heartbeat": True}},
        ]
        # No heartbeat user message → no filtering
        assert _filter_old_heartbeats(msgs) == msgs
