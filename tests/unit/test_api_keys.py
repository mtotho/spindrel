"""Unit tests for API key generation and scope checking."""
import pytest

from app.services.api_keys import generate_key, hash_key, has_scope, generate_api_docs


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

    def test_empty_scopes_returns_general_only(self):
        docs = generate_api_docs([])
        assert "/api/v1/discover" in docs  # scope=None, always included
        assert "POST" not in docs or "/chat" not in docs  # chat not included

    def test_admin_returns_all(self):
        docs = generate_api_docs(["admin"])
        assert "/chat" in docs
        assert "/api/v1/channels" in docs
        assert "/api/v1/tasks" in docs
