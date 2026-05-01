"""Tests for :mod:`app.services.backup_encryption` — the AES-256-CBC +
PBKDF2 envelope used to encrypt backup archives at rest.

The shell scripts ``scripts/backup.sh`` / ``scripts/restore.sh`` use
``openssl enc -aes-256-cbc -pbkdf2 -iter 100000`` with the same
parameters; this test suite pins:

1. round-trip correctness for the Python helpers,
2. byte-compatibility with openssl (when the binary is available), and
3. the read-only ``inspect_backup_dir`` audit helper.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.backup_encryption import (
    BackupArchiveStatus,
    decrypt_archive,
    encrypt_archive,
    inspect_backup_dir,
)


def test_round_trip_recovers_plaintext():
    plaintext = b"hello, encrypted backup world!\n" * 200
    blob = encrypt_archive(plaintext, "correct horse battery staple")
    assert blob.startswith(b"Salted__")
    assert blob != plaintext
    out = decrypt_archive(blob, "correct horse battery staple")
    assert out == plaintext


def test_wrong_passphrase_raises():
    plaintext = b"sensitive\n"
    blob = encrypt_archive(plaintext, "right-pass")
    with pytest.raises(ValueError):
        decrypt_archive(blob, "wrong-pass")


def test_empty_passphrase_rejected():
    with pytest.raises(ValueError):
        encrypt_archive(b"x", "")
    with pytest.raises(ValueError):
        decrypt_archive(b"Salted__\x00" * 4, "")


def test_decrypt_rejects_short_input():
    with pytest.raises(ValueError, match="too short"):
        decrypt_archive(b"too short", "pass")


def test_decrypt_rejects_missing_header():
    # Plaintext blob — no Salted__ prefix.
    body = b"\x00" * 64
    with pytest.raises(ValueError, match="missing Salted__"):
        decrypt_archive(body, "pass")


def test_each_encryption_uses_random_salt():
    plaintext = b"same content"
    blob_a = encrypt_archive(plaintext, "key")
    blob_b = encrypt_archive(plaintext, "key")
    assert blob_a != blob_b, "salt should be random per call"
    # But both decrypt to the same plaintext.
    assert decrypt_archive(blob_a, "key") == plaintext
    assert decrypt_archive(blob_b, "key") == plaintext


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")
def test_openssl_binary_can_decrypt_python_output(tmp_path: Path):
    """Cross-tool round-trip: encrypt with the Python helper, decrypt
    with the openssl binary that ``backup.sh`` invokes. Pins envelope
    compatibility — a future change to one side cannot drift silently."""
    plaintext = b"shell + python interop check\n" * 50
    blob = encrypt_archive(plaintext, "interop-key-12345")

    enc_path = tmp_path / "blob.enc"
    enc_path.write_bytes(blob)
    key_file = tmp_path / "key"
    key_file.write_bytes(b"interop-key-12345")
    key_file.chmod(0o600)

    out_path = tmp_path / "blob.dec"
    result = subprocess.run(
        [
            "openssl", "enc", "-d", "-aes-256-cbc",
            "-pbkdf2", "-iter", "100000",
            "-in", str(enc_path),
            "-out", str(out_path),
            "-pass", f"file:{key_file}",
        ],
        capture_output=True, check=False,
    )
    assert result.returncode == 0, (
        f"openssl decryption failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert out_path.read_bytes() == plaintext


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")
def test_python_can_decrypt_openssl_output(tmp_path: Path):
    """The other direction: openssl-encrypted archives must decrypt with
    the Python helper. Confirms admin tooling can inspect/rotate
    archives produced by the shell pipeline."""
    plaintext = b"openssl produced this payload\n" * 75
    src = tmp_path / "src"
    src.write_bytes(plaintext)
    enc = tmp_path / "src.enc"
    key_file = tmp_path / "key"
    key_file.write_bytes(b"interop-key-67890")
    key_file.chmod(0o600)

    subprocess.run(
        [
            "openssl", "enc", "-aes-256-cbc",
            "-salt", "-pbkdf2", "-iter", "100000",
            "-in", str(src),
            "-out", str(enc),
            "-pass", f"file:{key_file}",
        ],
        capture_output=True, check=True,
    )
    blob = enc.read_bytes()
    assert blob.startswith(b"Salted__")

    recovered = decrypt_archive(blob, "interop-key-67890")
    assert recovered == plaintext


def test_inspect_backup_dir_reports_encrypted_and_plaintext(tmp_path: Path):
    backups = tmp_path / "backups"
    backups.mkdir()
    # An encrypted archive (proper header).
    (backups / "agent-backup-20260501_010000.tar.gz.enc").write_bytes(
        b"Salted__" + os.urandom(64)
    )
    # A plaintext archive (legacy).
    (backups / "agent-backup-20260501_020000.tar.gz").write_bytes(
        b"\x1f\x8b\x08" + os.urandom(64)  # gzip magic, not strict-checked
    )
    # An ".enc" file with no Salted__ header — flagged as not-encrypted
    # so a stale truncated upload doesn't masquerade as encrypted.
    (backups / "agent-backup-20260501_030000.tar.gz.enc").write_bytes(
        b"NOTSALTED" + os.urandom(40)
    )
    # An unrelated file should be ignored.
    (backups / "README.md").write_text("ignored")

    statuses = inspect_backup_dir(backups)
    by_name = {s.name: s for s in statuses}

    assert "agent-backup-20260501_010000.tar.gz.enc" in by_name
    assert by_name["agent-backup-20260501_010000.tar.gz.enc"].encrypted is True

    assert "agent-backup-20260501_020000.tar.gz" in by_name
    assert by_name["agent-backup-20260501_020000.tar.gz"].encrypted is False

    assert "agent-backup-20260501_030000.tar.gz.enc" in by_name
    assert by_name["agent-backup-20260501_030000.tar.gz.enc"].encrypted is False

    assert "README.md" not in by_name


def test_inspect_backup_dir_returns_empty_for_missing_dir(tmp_path: Path):
    assert inspect_backup_dir(tmp_path / "does-not-exist") == []


def test_backup_archive_status_dataclass_fields(tmp_path: Path):
    backups = tmp_path / "backups"
    backups.mkdir()
    payload = b"Salted__" + b"\x00" * 64
    (backups / "agent-backup-20260501_040000.tar.gz.enc").write_bytes(payload)
    [status] = inspect_backup_dir(backups)
    assert isinstance(status, BackupArchiveStatus)
    assert status.size_bytes == len(payload)
    assert status.encrypted is True
