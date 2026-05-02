"""Migration 130 downgrade refuses to silently decrypt encrypted rows.

The migration was written to be reversible — but reversing it on a prod
instance that has accumulated encrypted writes is destructive (every
secret column is decrypted in place). The guard makes the operator opt
in via ALEMBIC_DOWNGRADE_FORCE=1.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "130_encrypt_secrets.py"
)


def _load_migration():
    """Import the alembic version file directly without going through
    alembic's runner, so we can call ``downgrade()`` against a stub
    connection without spinning up a real DB."""
    spec = importlib.util.spec_from_file_location("_mig130", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def fetchall(self):
        return []


class _FakeConnection:
    def __init__(self, encrypted_count: int):
        self._encrypted_count = encrypted_count
        self.executed: list[str] = []

    def execute(self, stmt, params=None):
        text = str(stmt)
        self.executed.append(text)
        if "AS total" in text:
            return _FakeResult(self._encrypted_count)
        # All other SELECTs return empty (no rows to actually decrypt) —
        # we only care that downgrade reaches them past the guard.
        return _FakeResult(0)


def _patch_alembic_op(conn):
    return patch.object(
        _load_migration(),
        "op",
        SimpleNamespace(get_bind=lambda: conn),
    )


@pytest.fixture
def migration():
    return _load_migration()


@pytest.fixture
def fake_fernet():
    """Stub fernet so _get_fernet() returns truthy and the guard is reached."""
    return SimpleNamespace(decrypt=lambda b: b)


def test_downgrade_proceeds_when_no_encrypted_rows(migration, fake_fernet, monkeypatch):
    monkeypatch.setattr(migration, "_get_fernet", lambda: fake_fernet)
    monkeypatch.delenv("ALEMBIC_DOWNGRADE_FORCE", raising=False)
    conn = _FakeConnection(encrypted_count=0)
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: conn))
    migration.downgrade()  # must not raise


def test_downgrade_refuses_when_encrypted_rows_present(migration, fake_fernet, monkeypatch):
    monkeypatch.setattr(migration, "_get_fernet", lambda: fake_fernet)
    monkeypatch.delenv("ALEMBIC_DOWNGRADE_FORCE", raising=False)
    conn = _FakeConnection(encrypted_count=7)
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: conn))
    with pytest.raises(RuntimeError, match="7 encrypted row"):
        migration.downgrade()


def test_downgrade_proceeds_when_force_flag_set(migration, fake_fernet, monkeypatch):
    monkeypatch.setattr(migration, "_get_fernet", lambda: fake_fernet)
    monkeypatch.setenv("ALEMBIC_DOWNGRADE_FORCE", "1")
    conn = _FakeConnection(encrypted_count=12)
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: conn))
    migration.downgrade()  # must not raise — operator opted in


def test_downgrade_skipped_without_key(migration, monkeypatch):
    """If no key is configured, downgrade no-ops without ever inspecting
    the DB; the guard isn't reached. Pre-existing behavior, pinned here
    so the new guard doesn't accidentally short-circuit first."""
    monkeypatch.setattr(migration, "_get_fernet", lambda: None)
    conn = _FakeConnection(encrypted_count=99)
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: conn))
    migration.downgrade()
    assert conn.executed == []
