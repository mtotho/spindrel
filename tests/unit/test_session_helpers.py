"""Unit tests for pure helpers in app.services.sessions."""
import uuid

from app.services.sessions import (
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
