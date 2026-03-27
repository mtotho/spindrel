"""Unit tests for API key generation and scope checking."""
import pytest

from app.services.api_keys import generate_key, hash_key, has_scope


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
