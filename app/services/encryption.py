"""Symmetric encryption for secrets stored in the database.

Uses Fernet (from the `cryptography` library) for authenticated encryption.
Encrypted values are stored with an "enc:" prefix so we can distinguish them
from legacy plaintext values and migrate incrementally.

Key management: set ENCRYPTION_KEY in .env to a Fernet-compatible base64 key.
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Strict mode: when ``settings.ENCRYPTION_STRICT`` is True (default in
production), :func:`encrypt` raises :class:`EncryptionNotConfiguredError` if
no key is configured instead of silently writing plaintext. The startup
bootstrap auto-generates a key on first boot, so reaching strict failure
means either a misconfigured key or a code path that bypasses bootstrap.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "enc:"


class EncryptionNotConfiguredError(RuntimeError):
    """Raised when encrypt()/decrypt() is called in strict mode without a key."""


_fernet: Fernet | None = None
_initialized = False


def _ensure_init() -> None:
    """Lazy-init: create the Fernet instance from settings on first use."""
    global _fernet, _initialized
    if _initialized:
        return
    _initialized = True
    from app.config import settings

    key = settings.ENCRYPTION_KEY
    if not key:
        return
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        logger.error("Invalid ENCRYPTION_KEY — encryption disabled")
        _fernet = None


def is_encryption_enabled() -> bool:
    """Return True if a valid ENCRYPTION_KEY is configured."""
    _ensure_init()
    return _fernet is not None


def _strict_mode() -> bool:
    """Return True if strict encryption mode is enabled."""
    try:
        from app.config import settings
        return bool(getattr(settings, "ENCRYPTION_STRICT", True))
    except Exception:
        return True


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns 'enc:<ciphertext>' if encryption is
    enabled.

    In strict mode (the default), raises :class:`EncryptionNotConfiguredError`
    when no valid key is configured. Outside strict mode, returns the
    plaintext unchanged for backward compatibility with legacy storage.
    """
    if not plaintext:
        return plaintext
    _ensure_init()
    if _fernet is None:
        if _strict_mode():
            raise EncryptionNotConfiguredError(
                "ENCRYPTION_KEY is not set or invalid; cannot store secret. "
                "Set ENCRYPTION_KEY in .env (the startup bootstrap will "
                "auto-generate one on first boot), or set "
                "ENCRYPTION_STRICT=false for ephemeral test/dev usage."
            )
        return plaintext
    token = _fernet.encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("utf-8")


def decrypt(value: str) -> str:
    """Decrypt a value. If it has the 'enc:' prefix, strip and decrypt.
    If no prefix (legacy plaintext), return as-is.

    If a value carries the encrypted prefix but no key is available, this
    raises in strict mode (so a forgotten key is a loud, recoverable error
    rather than silent corruption) and returns the raw ciphertext with a
    warning otherwise.
    """
    if not value:
        return value
    if not value.startswith(ENCRYPTED_PREFIX):
        return value

    _ensure_init()
    ciphertext = value[len(ENCRYPTED_PREFIX) :]
    if _fernet is None:
        if _strict_mode():
            raise EncryptionNotConfiguredError(
                "Encountered an encrypted value but ENCRYPTION_KEY is not "
                "configured. Set the original key in .env, or temporarily "
                "set ENCRYPTION_STRICT=false to read raw ciphertext."
            )
        logger.warning(
            "Encountered encrypted value but ENCRYPTION_KEY is not set — "
            "returning raw ciphertext (will not work as a valid secret)"
        )
        return ciphertext

    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt value — wrong key or corrupted ciphertext")
        raise ValueError("Failed to decrypt value — check ENCRYPTION_KEY")


def generate_key() -> str:
    """Generate a new Fernet encryption key (base64-encoded string)."""
    return Fernet.generate_key().decode()


def reset() -> None:
    """Reset module state (for testing)."""
    global _fernet, _initialized
    _fernet = None
    _initialized = False
