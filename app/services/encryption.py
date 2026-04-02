"""Symmetric encryption for secrets stored in the database.

Uses Fernet (from the `cryptography` library) for authenticated encryption.
Encrypted values are stored with an "enc:" prefix so we can distinguish them
from legacy plaintext values and migrate incrementally.

Key management: set ENCRYPTION_KEY in .env to a Fernet-compatible base64 key.
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If ENCRYPTION_KEY is not set, encrypt() returns plaintext and decrypt() passes
through — the system degrades gracefully to unencrypted storage.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "enc:"

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


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns 'enc:<ciphertext>' if encryption is
    enabled, otherwise returns the plaintext unchanged."""
    if not plaintext:
        return plaintext
    _ensure_init()
    if _fernet is None:
        return plaintext
    token = _fernet.encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("utf-8")


def decrypt(value: str) -> str:
    """Decrypt a value. If it has the 'enc:' prefix, strip and decrypt.
    If no prefix (legacy plaintext), return as-is. Handles missing key
    gracefully by returning the raw value with a warning."""
    if not value:
        return value
    if not value.startswith(ENCRYPTED_PREFIX):
        return value

    _ensure_init()
    ciphertext = value[len(ENCRYPTED_PREFIX) :]
    if _fernet is None:
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


def reset() -> None:
    """Reset module state (for testing)."""
    global _fernet, _initialized
    _fernet = None
    _initialized = False
