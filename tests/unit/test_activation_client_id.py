"""Tests for activation client_id resolution."""
import uuid
from unittest.mock import patch

import pytest

from app.services.channel_integrations import resolve_activation_client_id


CHANNEL_ID = uuid.uuid4()


def test_auto_client_id_from_settings():
    """Gmail-style: auto_client_id template resolves from integration settings."""
    binding_meta = {
        "gmail": {
            "client_id_prefix": "gmail:",
            "auto_client_id": "gmail:{GMAIL_EMAIL}",
        }
    }
    with (
        patch("app.services.integration_catalog.discover_binding_metadata", return_value=binding_meta),
        patch("app.services.integration_settings.get_value", return_value="user@gmail.com"),
    ):
        result = resolve_activation_client_id("gmail", CHANNEL_ID)

    assert result == "gmail:user@gmail.com"


def test_falls_back_when_setting_empty():
    """If the setting is empty, fall back to mc-activated."""
    binding_meta = {
        "gmail": {
            "client_id_prefix": "gmail:",
            "auto_client_id": "gmail:{GMAIL_EMAIL}",
        }
    }
    with (
        patch("app.services.integration_catalog.discover_binding_metadata", return_value=binding_meta),
        patch("app.services.integration_settings.get_value", return_value=""),
    ):
        result = resolve_activation_client_id("gmail", CHANNEL_ID)

    assert result.startswith("mc-activated:") and result.endswith(str(CHANNEL_ID))


def test_falls_back_when_no_binding():
    """Integration without binding config uses mc-activated."""
    with patch("app.services.integration_catalog.discover_binding_metadata", return_value={}):
        result = resolve_activation_client_id("excalidraw", CHANNEL_ID)

    assert result.startswith("mc-activated:") and result.endswith(str(CHANNEL_ID))


def test_falls_back_when_no_auto_client_id():
    """Integration with binding but no auto_client_id uses mc-activated."""
    binding_meta = {
        "slack": {
            "client_id_prefix": "slack:",
            # no auto_client_id — Slack needs user to specify the channel
        }
    }
    with patch("app.services.integration_catalog.discover_binding_metadata", return_value=binding_meta):
        result = resolve_activation_client_id("slack", CHANNEL_ID)

    assert result.startswith("mc-activated:") and result.endswith(str(CHANNEL_ID))


def test_multiple_placeholders():
    """Template with multiple placeholders should all be resolved."""
    binding_meta = {
        "custom": {
            "client_id_prefix": "custom:",
            "auto_client_id": "custom:{HOST}:{PORT}",
        }
    }

    def mock_get_value(integration_id, key):
        return {"HOST": "example.com", "PORT": "8080"}.get(key, "")

    with (
        patch("app.services.integration_catalog.discover_binding_metadata", return_value=binding_meta),
        patch("app.services.integration_settings.get_value", side_effect=mock_get_value),
    ):
        result = resolve_activation_client_id("custom", CHANNEL_ID)

    assert result == "custom:example.com:8080"
