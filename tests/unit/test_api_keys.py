"""Unit tests for API key generation and scope checking."""
import json

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.services.api_keys import generate_key, hash_key, has_scope, generate_api_docs
from app.services import api_keys as _api_keys_mod


@pytest.fixture(autouse=True, scope="module")
def _populate_catalog():
    """Build the endpoint catalog from the real app so generate_api_docs tests work."""
    from app.main import app
    from app.services.endpoint_catalog import build_endpoint_catalog
    _api_keys_mod.ENDPOINT_CATALOG = build_endpoint_catalog(app)


class TestGenerateKey:
    def test_format(self):
        full_key, prefix, key_hash = generate_key()
        assert full_key.startswith("ask_")
        assert len(full_key) == 68  # "ask_" + 64 hex chars
        assert prefix == full_key[:12]
        assert len(key_hash) == 64  # SHA-256 hex digest

    def test_uniqueness(self):
        keys = [generate_key() for _ in range(10)]
        full_keys = [k[0] for k in keys]
        assert len(set(full_keys)) == 10  # all unique

    def test_hash_consistency(self):
        full_key, _, key_hash = generate_key()
        assert hash_key(full_key) == key_hash


class TestHasScope:
    def test_exact_match(self):
        assert has_scope(["chat"], "chat") is True

    def test_no_match(self):
        assert has_scope(["chat"], "channels:read") is False

    def test_admin_bypasses_all(self):
        assert has_scope(["admin"], "chat") is True
        assert has_scope(["admin"], "channels:write") is True
        assert has_scope(["admin"], "settings:read") is True

    def test_write_implies_read(self):
        assert has_scope(["channels:write"], "channels:read") is True
        assert has_scope(["tasks:write"], "tasks:read") is True
        assert has_scope(["providers:write"], "providers:read") is True

    def test_read_does_not_imply_write(self):
        assert has_scope(["channels:read"], "channels:write") is False

    def test_empty_scopes(self):
        assert has_scope([], "chat") is False
        assert has_scope([], "admin") is False

    def test_multiple_scopes(self):
        scopes = ["chat", "channels:read", "tasks:write"]
        assert has_scope(scopes, "chat") is True
        assert has_scope(scopes, "channels:read") is True
        assert has_scope(scopes, "tasks:read") is True  # write implies read
        assert has_scope(scopes, "tasks:write") is True
        assert has_scope(scopes, "channels:write") is False
        assert has_scope(scopes, "providers:read") is False

    def test_write_implies_read_only_same_resource(self):
        assert has_scope(["channels:write"], "tasks:read") is False

    def test_broader_scope_covers_narrower(self):
        """e.g. 'channels:write' covers 'channels:write:abc123' (resource-level)."""
        assert has_scope(["channels:write"], "channels:write:abc123") is True
        assert has_scope(["channels:read"], "channels:read:abc123") is True

    def test_narrower_does_not_cover_broader(self):
        """Resource-level scope doesn't grant access to other resources."""
        assert has_scope(["channels:read:abc123"], "channels:read") is False

    def test_wildcard_scope(self):
        """Wildcard scope covers all actions on that resource."""
        assert has_scope(["channels:*"], "channels:read") is True
        assert has_scope(["channels:*"], "channels:write") is True
        assert has_scope(["channels:*"], "channels:write:abc") is True

    def test_wildcard_does_not_cross_resources(self):
        assert has_scope(["channels:*"], "tasks:read") is False

    # --- Hierarchical parent.child scopes ---

    def test_parent_covers_child_same_action(self):
        """'channels:write' covers 'channels.messages:write'."""
        assert has_scope(["channels:write"], "channels.messages:write") is True
        assert has_scope(["channels:read"], "channels.messages:read") is True
        assert has_scope(["channels:read"], "channels.config:read") is True
        assert has_scope(["workspaces:write"], "workspaces.files:write") is True

    def test_parent_write_covers_child_read(self):
        """'channels:write' covers 'channels.messages:read' (write implies read + parent covers child)."""
        assert has_scope(["channels:write"], "channels.messages:read") is True
        assert has_scope(["channels:write"], "channels.config:read") is True

    def test_parent_read_does_not_cover_child_write(self):
        """'channels:read' does NOT cover 'channels.messages:write'."""
        assert has_scope(["channels:read"], "channels.messages:write") is False

    def test_child_does_not_cover_parent(self):
        """'channels.messages:write' does NOT cover 'channels:write'."""
        assert has_scope(["channels.messages:write"], "channels:write") is False
        assert has_scope(["channels.messages:read"], "channels:read") is False

    def test_child_does_not_cover_sibling(self):
        """'channels.messages:write' does NOT cover 'channels.config:write'."""
        assert has_scope(["channels.messages:write"], "channels.config:write") is False

    def test_wildcard_covers_child_resources(self):
        """'channels:*' covers 'channels.messages:read' etc."""
        assert has_scope(["channels:*"], "channels.messages:read") is True
        assert has_scope(["channels:*"], "channels.messages:write") is True
        assert has_scope(["channels:*"], "channels.config:write") is True
        assert has_scope(["channels:*"], "channels.integrations:read") is True

    def test_granular_scope_exact_match(self):
        """Granular scopes work by exact match."""
        assert has_scope(["channels.messages:write"], "channels.messages:write") is True
        assert has_scope(["channels.config:read"], "channels.config:read") is True

    def test_granular_write_implies_read(self):
        """Write implies read for granular sub-resources."""
        assert has_scope(["channels.messages:write"], "channels.messages:read") is True
        assert has_scope(["workspaces.files:write"], "workspaces.files:read") is True


class TestGenerateApiDocs:
    def test_full_access_returns_all(self):
        docs = generate_api_docs(None)
        assert "# Agent Server API Reference" in docs
        assert "/chat" in docs
        assert "/api/v1/channels" in docs

    def test_scoped_filters(self):
        docs = generate_api_docs(["chat"])
        assert "/chat" in docs
        # Should not include channels endpoints
        assert "channels:write" not in docs

    def test_empty_scopes_returns_minimal(self):
        docs = generate_api_docs([])
        # With no scopes, only unscoped endpoints should be included
        assert "### `POST /chat`" not in docs  # chat endpoint not included
        assert "### `GET /api/v1/admin/bots" not in docs  # admin not included

    def test_admin_returns_all(self):
        docs = generate_api_docs(["admin"])
        assert "/chat" in docs
        assert "/api/v1/channels" in docs
        assert "/api/v1/tasks" in docs


class TestApiAccessToolsIntegration:
    """Test that list_api_endpoints and call_api work with the scope system."""

    @pytest.mark.asyncio
    async def test_list_api_endpoints_uses_scope_filtering(self):
        """list_api_endpoints filters ENDPOINT_CATALOG by bot's api_permissions."""
        from app.tools.local.api_access import list_api_endpoints
        from app.agent.context import current_bot_id

        mock_bot = MagicMock()
        mock_bot.id = "test_bot"
        mock_bot.api_permissions = ["channels:read"]

        token = current_bot_id.set("test_bot")
        try:
            with patch("app.agent.bots.get_bot", return_value=mock_bot):
                result = json.loads(await list_api_endpoints())
            assert result["count"] > 0
            # Should include channel endpoints
            paths = [ep["path"] for ep in result["endpoints"]]
            assert any("/channels" in p for p in paths)
            # Should NOT include standalone task endpoints (no tasks scope)
            # (channel sub-paths like /channels/{id}/tasks are OK)
            assert not any(p.startswith("/api/v1/tasks") or p.startswith("/api/v1/admin/tasks") for p in paths)
        finally:
            current_bot_id.reset(token)
