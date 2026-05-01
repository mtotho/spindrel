"""Tests for app.services.encryption — Fernet-based secret encryption."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.services import encryption


@pytest.fixture(autouse=True)
def _reset_encryption():
    """Reset module state before each test."""
    encryption.reset()
    yield
    encryption.reset()


def _make_settings(key: str = "", strict: bool = False):
    """Return a mock settings object with the given ENCRYPTION_KEY."""

    class FakeSettings:
        ENCRYPTION_KEY = key
        ENCRYPTION_STRICT = strict

    return FakeSettings()


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip():
    key = Fernet.generate_key().decode()
    with patch("app.services.encryption.settings", _make_settings(key), create=True):
        # Re-patch the lazy import inside _ensure_init
        with patch.dict("sys.modules", {}):
            encryption.reset()
            with patch("app.config.settings", _make_settings(key)):
                encrypted = encryption.encrypt("my-secret-key-123")
                assert encrypted.startswith("enc:")
                assert encryption.decrypt(encrypted) == "my-secret-key-123"


def test_encrypt_decrypt_with_special_chars():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        secret = "p@$$w0rd!#&*()=+[]{}|;:',.<>?/`~"
        encrypted = encryption.encrypt(secret)
        assert encryption.decrypt(encrypted) == secret


def test_encrypt_decrypt_unicode():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        secret = "密码🔑clé"
        encrypted = encryption.encrypt(secret)
        assert encryption.decrypt(encrypted) == secret


# ---------------------------------------------------------------------------
# No key → plaintext passthrough
# ---------------------------------------------------------------------------


def test_encrypt_no_key_returns_plaintext():
    with patch("app.config.settings", _make_settings("")):
        encryption.reset()
        assert encryption.encrypt("hello") == "hello"


def test_decrypt_no_key_plaintext_passthrough():
    with patch("app.config.settings", _make_settings("")):
        encryption.reset()
        assert encryption.decrypt("hello") == "hello"


def test_is_encryption_enabled_false_without_key():
    with patch("app.config.settings", _make_settings("")):
        encryption.reset()
        assert encryption.is_encryption_enabled() is False


def test_is_encryption_enabled_true_with_key():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        assert encryption.is_encryption_enabled() is True


# ---------------------------------------------------------------------------
# Empty / None handling
# ---------------------------------------------------------------------------


def test_encrypt_empty_string():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        assert encryption.encrypt("") == ""


def test_decrypt_empty_string():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        assert encryption.decrypt("") == ""


# ---------------------------------------------------------------------------
# Prefix detection
# ---------------------------------------------------------------------------


def test_decrypt_plaintext_without_prefix():
    """Values without 'enc:' prefix should pass through unchanged."""
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        assert encryption.decrypt("sk-abc123") == "sk-abc123"


def test_encrypted_value_has_prefix():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        result = encryption.encrypt("test")
        assert result.startswith("enc:")
        # The ciphertext part should be valid base64
        assert len(result) > len("enc:")


# ---------------------------------------------------------------------------
# Wrong key / invalid ciphertext
# ---------------------------------------------------------------------------


def test_decrypt_wrong_key_raises():
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key1)):
        encryption.reset()
        encrypted = encryption.encrypt("secret")

    # Now try to decrypt with a different key
    with patch("app.config.settings", _make_settings(key2)):
        encryption.reset()
        with pytest.raises(ValueError, match="Failed to decrypt"):
            encryption.decrypt(encrypted)


def test_decrypt_corrupted_ciphertext_raises():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        with pytest.raises(ValueError, match="Failed to decrypt"):
            encryption.decrypt("enc:not-valid-ciphertext")


# ---------------------------------------------------------------------------
# Encrypted value + no key (key removed after encryption)
# ---------------------------------------------------------------------------


def test_decrypt_encrypted_value_without_key_warns():
    """If key is removed after values were encrypted, decrypt returns raw ciphertext with warning."""
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key)):
        encryption.reset()
        encrypted = encryption.encrypt("secret")

    # Now no key available
    with patch("app.config.settings", _make_settings("")):
        encryption.reset()
        # Should return the ciphertext portion (not the enc: prefix) — won't be usable as a secret
        result = encryption.decrypt(encrypted)
        assert result == encrypted[len("enc:"):]


# ---------------------------------------------------------------------------
# Invalid ENCRYPTION_KEY
# ---------------------------------------------------------------------------


def test_invalid_key_disables_encryption():
    with patch("app.config.settings", _make_settings("not-a-valid-fernet-key")):
        encryption.reset()
        assert encryption.is_encryption_enabled() is False
        # Should fall through to plaintext
        assert encryption.encrypt("hello") == "hello"


# ---------------------------------------------------------------------------
# Strict mode — fail-fast when encrypt() is called without a key
# ---------------------------------------------------------------------------


def test_strict_mode_raises_on_missing_key():
    with patch("app.config.settings", _make_settings(key="", strict=True)):
        encryption.reset()
        with pytest.raises(encryption.EncryptionNotConfiguredError):
            encryption.encrypt("would-be-secret")


def test_strict_mode_raises_on_invalid_key():
    with patch("app.config.settings", _make_settings(key="not-a-fernet-key", strict=True)):
        encryption.reset()
        with pytest.raises(encryption.EncryptionNotConfiguredError):
            encryption.encrypt("would-be-secret")


def test_strict_mode_decrypt_raises_when_value_is_encrypted_but_no_key():
    """In strict mode, an enc:-prefixed value with no key is a loud error."""
    with patch("app.config.settings", _make_settings(key="", strict=True)):
        encryption.reset()
        with pytest.raises(encryption.EncryptionNotConfiguredError):
            encryption.decrypt("enc:gAAAAABh-bogus")


def test_strict_mode_passthrough_for_legacy_plaintext():
    """Strict mode does NOT disrupt reads of legacy plaintext values."""
    with patch("app.config.settings", _make_settings(key="", strict=True)):
        encryption.reset()
        # No 'enc:' prefix → still a valid legacy value, return as-is
        assert encryption.decrypt("legacy-plaintext") == "legacy-plaintext"


def test_strict_mode_with_key_round_trips_normally():
    key = Fernet.generate_key().decode()
    with patch("app.config.settings", _make_settings(key=key, strict=True)):
        encryption.reset()
        encrypted = encryption.encrypt("secret")
        assert encrypted.startswith("enc:")
        assert encryption.decrypt(encrypted) == "secret"


def test_non_strict_mode_legacy_passthrough_preserved():
    """Existing tests/dev workflows that rely on plaintext fallback still work."""
    with patch("app.config.settings", _make_settings(key="", strict=False)):
        encryption.reset()
        assert encryption.encrypt("hello") == "hello"
        assert encryption.decrypt("hello") == "hello"
        assert encryption.decrypt("enc:bogus") == "bogus"
