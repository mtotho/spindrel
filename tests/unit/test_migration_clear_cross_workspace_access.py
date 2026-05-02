"""Migration 287 strips the deprecated cross_workspace_access key from
every bot's delegation_config without disturbing the rest of the
config.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "287_clear_cross_workspace_access.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mig287", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConnection:
    """Stub of an alembic-bound SQL connection that records UPDATEs."""

    def __init__(self, rows):
        # rows is list of SimpleNamespace(id=..., delegation_config=...)
        self._rows = rows
        self.updates: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        text = str(stmt).lower()
        if "select id" in text and "from bots" in text:
            return _FakeResult(self._rows)
        if "update bots" in text:
            self.updates.append((str(stmt), params or {}))
            return _FakeResult([])
        return _FakeResult([])


@pytest.fixture
def migration():
    return _load_migration()


def _patch_op(migration, conn):
    return patch.object(
        migration,
        "op",
        SimpleNamespace(get_bind=lambda: conn),
    )


def test_strips_key_and_preserves_other_delegation_config(migration):
    rows = [
        SimpleNamespace(
            id="bot-1",
            delegation_config={
                "cross_workspace_access": True,
                "delegate_bots": ["sidekick"],
            },
        ),
    ]
    conn = _FakeConnection(rows)
    with _patch_op(migration, conn):
        migration.upgrade()
    assert len(conn.updates) == 1
    payload = json.loads(conn.updates[0][1]["val"])
    assert "cross_workspace_access" not in payload
    assert payload["delegate_bots"] == ["sidekick"]
    assert conn.updates[0][1]["id"] == "bot-1"


def test_skips_rows_without_the_key(migration):
    rows = [
        SimpleNamespace(
            id="bot-1",
            delegation_config={"delegate_bots": ["sidekick"]},
        ),
    ]
    conn = _FakeConnection(rows)
    with _patch_op(migration, conn):
        migration.upgrade()
    assert conn.updates == []


def test_handles_json_string_delegation_config(migration):
    rows = [
        SimpleNamespace(
            id="bot-1",
            delegation_config=json.dumps(
                {"cross_workspace_access": True, "delegate_bots": []}
            ),
        ),
    ]
    conn = _FakeConnection(rows)
    with _patch_op(migration, conn):
        migration.upgrade()
    assert len(conn.updates) == 1
    payload = json.loads(conn.updates[0][1]["val"])
    assert "cross_workspace_access" not in payload
    assert payload["delegate_bots"] == []


def test_no_rows_no_updates(migration):
    conn = _FakeConnection([])
    with _patch_op(migration, conn):
        migration.upgrade()
    assert conn.updates == []


def test_downgrade_is_noop(migration):
    conn = _FakeConnection([])
    with _patch_op(migration, conn):
        migration.downgrade()  # must not raise
    assert conn.updates == []
