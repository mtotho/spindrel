"""Backup-archive encryption helpers.

The actual backup pipeline lives in ``scripts/backup.sh`` /
``scripts/restore.sh`` and uses ``openssl enc -aes-256-cbc -pbkdf2 -iter
100000`` for the on-disk envelope. This module exposes:

1. A pure-Python round-trip (``encrypt_archive`` /
   ``decrypt_archive``) that produces a byte-compatible envelope so the
   shell scripts and Python tests stay aligned, and so admin tooling can
   inspect or rotate backups without shelling out to openssl.

2. A read-only audit helper (``inspect_backup_dir``) used by the
   security-audit endpoint to surface plaintext archives in
   ``backups/`` — operators see whether their backup posture matches
   the strict-mode encryption posture the live app uses.

The chosen primitive — AES-256-CBC + PBKDF2(SHA-256, 100k iters) over a
random 8-byte salt + 16-byte IV — matches openssl's modern envelope
format::

    Salted__<8-byte salt><openssl-pbkdf2-derived AES key||IV><AES-CBC ciphertext>

We deliberately use the openssl envelope (not Fernet) so the shell
scripts and Python helpers are interchangeable. The key derivation
parameters mirror the shell scripts; changing them in one place
requires changing both.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

__all__ = [
    "BackupArchiveStatus",
    "decrypt_archive",
    "encrypt_archive",
    "inspect_backup_dir",
]


_SALT_HEADER = b"Salted__"
_SALT_LEN = 8
_KEY_LEN = 32  # AES-256
_IV_LEN = 16
_PBKDF2_ITERS = 100_000


def _derive_key_iv(passphrase: bytes, salt: bytes) -> tuple[bytes, bytes]:
    """Mirror ``openssl enc -pbkdf2`` key derivation (KDF = PBKDF2-HMAC-SHA256,
    output split into ``key || iv``)."""
    kdf_out = hashlib.pbkdf2_hmac(
        "sha256", passphrase, salt, _PBKDF2_ITERS, dklen=_KEY_LEN + _IV_LEN,
    )
    return kdf_out[:_KEY_LEN], kdf_out[_KEY_LEN:_KEY_LEN + _IV_LEN]


def encrypt_archive(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt ``plaintext`` to the openssl ``Salted__`` envelope.

    Used by tests + admin tooling. The shell script uses ``openssl enc``
    with the same parameters — output is byte-compatible.
    """
    if not passphrase:
        raise ValueError("backup_encryption: passphrase must not be empty")
    salt = os.urandom(_SALT_LEN)
    key, iv = _derive_key_iv(passphrase.encode("utf-8"), salt)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return _SALT_HEADER + salt + ciphertext


def decrypt_archive(ciphertext: bytes, passphrase: str) -> bytes:
    """Decrypt an openssl ``Salted__`` envelope. Raises ``ValueError`` on
    a malformed header or wrong passphrase (CBC padding check)."""
    if not passphrase:
        raise ValueError("backup_encryption: passphrase must not be empty")
    if len(ciphertext) < len(_SALT_HEADER) + _SALT_LEN + _IV_LEN:
        raise ValueError("backup_encryption: archive too short to be encrypted")
    if not ciphertext.startswith(_SALT_HEADER):
        raise ValueError("backup_encryption: missing Salted__ header — archive is not encrypted")
    salt = ciphertext[len(_SALT_HEADER):len(_SALT_HEADER) + _SALT_LEN]
    body = ciphertext[len(_SALT_HEADER) + _SALT_LEN:]
    key, iv = _derive_key_iv(passphrase.encode("utf-8"), salt)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(body) + decryptor.finalize()
    try:
        unpadder = PKCS7(algorithms.AES.block_size).unpadder()
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise ValueError(
            "backup_encryption: decryption failed — wrong passphrase or corrupt archive"
        ) from exc


@dataclass(frozen=True)
class BackupArchiveStatus:
    """Read-only summary of one archive in ``backups/``."""

    name: str
    encrypted: bool
    size_bytes: int


def inspect_backup_dir(backup_dir: Path) -> list[BackupArchiveStatus]:
    """Return a list of (name, encrypted, size) for every archive in
    ``backup_dir``. ``encrypted`` is ``True`` when the file ends with
    ``.enc`` AND its first 8 bytes are the ``Salted__`` header (the
    extension alone is treated as a hint, not authority).

    Returns an empty list when the directory does not exist.
    """
    if not backup_dir.is_dir():
        return []
    out: list[BackupArchiveStatus] = []
    for path in sorted(backup_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if not name.startswith("agent-backup-"):
            continue
        if not (name.endswith(".tar.gz") or name.endswith(".tar.gz.enc")):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        encrypted = False
        if name.endswith(".tar.gz.enc"):
            try:
                with path.open("rb") as fh:
                    encrypted = fh.read(len(_SALT_HEADER)) == _SALT_HEADER
            except OSError:
                encrypted = False
        out.append(BackupArchiveStatus(name=name, encrypted=encrypted, size_bytes=size))
    return out
