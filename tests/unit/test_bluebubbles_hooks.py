"""Tests for BlueBubbles hooks — resolve_dispatch_config."""
import pytest
from unittest.mock import patch, MagicMock


class TestResolveDispatchConfig:
    """Test _resolve_dispatch_config builds correct BB dispatch_config."""

    def _resolve(self, client_id: str):
        from integrations.bluebubbles.hooks import _resolve_dispatch_config
        return _resolve_dispatch_config(client_id)

    @patch("app.services.integration_settings.get_value")
    def test_resolves_from_db_settings(self, mock_get):
        """Should build config from IntegrationSetting DB cache."""
        mock_get.side_effect = lambda iid, key: {
            "BLUEBUBBLES_SERVER_URL": "http://10.0.0.1:1234",
            "BLUEBUBBLES_PASSWORD": "secret",
        }.get(key)

        result = self._resolve("bb:iMessage;-;+15551234567")
        assert result == {
            "type": "bluebubbles",
            "chat_guid": "iMessage;-;+15551234567",
            "server_url": "http://10.0.0.1:1234",
            "password": "secret",
        }

    @patch.dict("os.environ", {
        "BLUEBUBBLES_SERVER_URL": "http://env.host:1234",
        "BLUEBUBBLES_PASSWORD": "envpass",
    })
    @patch("app.services.integration_settings.get_value", return_value=None)
    def test_falls_back_to_env_vars(self, mock_get):
        """Falls back to os.environ when DB settings are empty."""
        result = self._resolve("bb:iMessage;+;chat999")
        assert result == {
            "type": "bluebubbles",
            "chat_guid": "iMessage;+;chat999",
            "server_url": "http://env.host:1234",
            "password": "envpass",
        }

    @patch("app.services.integration_settings.get_value", return_value=None)
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_when_no_credentials(self, mock_get):
        """Returns None when neither DB nor env has credentials."""
        result = self._resolve("bb:iMessage;-;+15551234567")
        assert result is None

    def test_returns_none_for_non_bb_prefix(self):
        """Returns None for client_ids that don't start with bb:."""
        result = self._resolve("slack:C01ABC")
        assert result is None

    def test_returns_none_for_empty_chat_guid(self):
        """Returns None when client_id is just 'bb:' with no chat GUID."""
        result = self._resolve("bb:")
        assert result is None

    @patch("app.services.integration_settings.get_value")
    def test_db_partial_falls_back_to_env(self, mock_get):
        """If DB has server_url but not password, uses env for password."""
        mock_get.side_effect = lambda iid, key: {
            "BLUEBUBBLES_SERVER_URL": "http://db.host:1234",
            "BLUEBUBBLES_PASSWORD": None,
        }.get(key)
        with patch.dict("os.environ", {"BLUEBUBBLES_PASSWORD": "envpass"}):
            result = self._resolve("bb:iMessage;-;+15551234567")
            assert result is not None
            assert result["server_url"] == "http://db.host:1234"
            assert result["password"] == "envpass"


class TestIntegrationMetaRegistration:
    """Test that BB hooks register correctly."""

    def test_meta_registered_with_resolve_dispatch_config(self):
        from app.agent.hooks import get_integration_meta
        # Import hooks to trigger registration
        import integrations.bluebubbles.hooks  # noqa: F401
        meta = get_integration_meta("bluebubbles")
        assert meta is not None
        assert meta.client_id_prefix == "bb:"
        assert meta.resolve_dispatch_config is not None
