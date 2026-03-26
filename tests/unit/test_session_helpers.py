"""Unit tests for pure helpers in app.services.sessions."""
import uuid
from types import SimpleNamespace

from app.services.sessions import (
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

    def test_no_tool_calls_none_content_omits_key(self):
        msg = _fake_message(content=None, tool_calls=None)
        d = _message_to_dict(msg)
        assert "content" not in d
