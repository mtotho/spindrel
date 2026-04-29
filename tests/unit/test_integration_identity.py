"""Unit tests for integration identity field discovery."""
import pytest
from unittest.mock import patch, MagicMock
from types import ModuleType


class TestDiscoverIdentityFields:
    def test_returns_slack_fields(self):
        """Real discovery should find integrations/slack/config.py."""
        from integrations import discover_identity_fields
        results = discover_identity_fields()
        # Should include slack if config.py exists
        slack = next((r for r in results if r["id"] == "slack"), None)
        assert slack is not None
        assert slack["name"] == "Slack"
        assert len(slack["fields"]) >= 1
        assert slack["fields"][0]["key"] == "user_id"

    def test_returns_empty_when_no_config(self):
        """Discovery with no config.py files returns empty list."""
        from integrations import discover_identity_fields
        with patch("integrations.discovery._INTEGRATIONS_DIR") as mock_dir:
            mock_dir.iterdir.return_value = []
            results = discover_identity_fields()
        assert results == []


class TestSlackConfig:
    def test_identity_fields_shape(self):
        from integrations.slack.config import IDENTITY_FIELDS
        assert isinstance(IDENTITY_FIELDS, list)
        assert len(IDENTITY_FIELDS) >= 1
        field = IDENTITY_FIELDS[0]
        assert "key" in field
        assert "label" in field
        assert "description" in field
        assert field["key"] == "user_id"
