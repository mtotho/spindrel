"""Tests for app.services.integration_manifests.

Focus: YAML manifests are seeded on first startup and updated when the
file content changes on disk.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects.postgresql import Insert as PgInsert

from app.services.integration_manifests import (
    _file_hash,
    seed_manifests,
)


# ---------------------------------------------------------------------------
# _file_hash — content drift detection
# ---------------------------------------------------------------------------


class TestFileHash:
    def test_hash_changes_when_file_changes(self, tmp_path):
        f = tmp_path / "integration.yaml"
        f.write_text("id: foo\nname: Foo\n")
        h1 = _file_hash(f)

        f.write_text("id: foo\nname: Foo\nsettings: []\n")
        h2 = _file_hash(f)

        assert h1 != h2

    def test_hash_stable_when_file_unchanged(self, tmp_path):
        f = tmp_path / "integration.yaml"
        f.write_text("id: foo\n")
        assert _file_hash(f) == _file_hash(f)


# ---------------------------------------------------------------------------
# seed_manifests — YAML seeding
# ---------------------------------------------------------------------------


def _insert_values(stmt) -> dict:
    """Extract a {column_name: python_value} dict from a pg_insert statement."""
    return {col.name: bind.value for col, bind in stmt._values.items()}


def _make_yaml_integration(tmp_path: Path, integration_id: str, extra_yaml: str = "") -> Path:
    """Build a temporary integration directory with an integration.yaml file."""
    intg_dir = tmp_path / integration_id
    intg_dir.mkdir()
    base = textwrap.dedent(f"""\
        id: {integration_id}
        name: {integration_id.replace('_', ' ').title()}
        icon: Plug
        description: "Test integration"
        version: "1.0"
    """)
    yaml_content = base + extra_yaml
    (intg_dir / "integration.yaml").write_text(yaml_content)
    return intg_dir


class _CapturingSession:
    """AsyncMock-like session that records every statement passed to execute()."""

    def __init__(self, existing_row=None):
        self.executed = []
        self.committed = False
        self._existing_row = existing_row

    async def execute(self, stmt):
        self.executed.append(stmt)
        return MagicMock()

    async def get(self, _model, _pk):
        return self._existing_row

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_seed_manifests_first_time_inserts_yaml_row(tmp_path):
    """First-ever seed for a YAML integration: INSERT executed."""
    intg_dir = _make_yaml_integration(tmp_path, "fooarr")
    session = _CapturingSession(existing_row=None)

    with patch(
        "integrations._iter_integration_candidates",
        return_value=[(intg_dir, "fooarr", False, "integration")],
    ), patch(
        "app.db.engine.async_session",
        return_value=session,
    ):
        await seed_manifests()

    assert session.committed
    assert len(session.executed) == 1
    stmt = session.executed[0]
    assert isinstance(stmt, PgInsert)

    extracted = _insert_values(stmt)
    assert extracted["id"] == "fooarr"
    assert extracted["source"] == "yaml"
    assert extracted["content_hash"]  # non-empty
    assert extracted["yaml_content"]  # non-empty


@pytest.mark.asyncio
async def test_seed_manifests_yaml_change_updates_row(tmp_path, caplog):
    """When YAML content hash differs from existing row, the row is updated."""
    intg_dir = _make_yaml_integration(tmp_path, "fooarr")

    existing = MagicMock()
    existing.content_hash = "stale-hash-from-prior-startup"
    existing.source = "yaml"
    session = _CapturingSession(existing_row=existing)

    import logging
    caplog.set_level(logging.INFO, logger="app.services.integration_manifests")
    with patch(
        "integrations._iter_integration_candidates",
        return_value=[(intg_dir, "fooarr", False, "integration")],
    ), patch(
        "app.db.engine.async_session",
        return_value=session,
    ):
        await seed_manifests()

    # The row was updated in-place (no INSERT statement, just attribute mutation)
    assert session.committed
    update_logs = [r for r in caplog.records if "Updated manifest" in r.message]
    assert len(update_logs) == 1
    assert "fooarr" in update_logs[0].message


@pytest.mark.asyncio
async def test_seed_manifests_unchanged_yaml_no_update(tmp_path, caplog):
    """When YAML content hash matches existing row, nothing happens."""
    intg_dir = _make_yaml_integration(tmp_path, "fooarr")
    current_hash = _file_hash(intg_dir / "integration.yaml")

    existing = MagicMock()
    existing.content_hash = current_hash
    existing.source = "yaml"
    session = _CapturingSession(existing_row=existing)

    import logging
    caplog.set_level(logging.INFO, logger="app.services.integration_manifests")
    with patch(
        "integrations._iter_integration_candidates",
        return_value=[(intg_dir, "fooarr", False, "integration")],
    ), patch(
        "app.db.engine.async_session",
        return_value=session,
    ):
        await seed_manifests()

    # No INSERT and no update log
    assert len(session.executed) == 0
    update_logs = [r for r in caplog.records if "Updated manifest" in r.message]
    assert update_logs == []


@pytest.mark.asyncio
async def test_seed_manifests_skips_dir_without_yaml(tmp_path):
    """Directories without integration.yaml are skipped."""
    intg_dir = tmp_path / "barint"
    intg_dir.mkdir()
    (intg_dir / "__init__.py").write_text("")
    # No integration.yaml

    session = _CapturingSession(existing_row=None)

    with patch(
        "integrations._iter_integration_candidates",
        return_value=[(intg_dir, "barint", False, "integration")],
    ), patch(
        "app.db.engine.async_session",
        return_value=session,
    ):
        await seed_manifests()

    assert session.committed
    assert len(session.executed) == 0


@pytest.mark.asyncio
async def test_seed_manifests_settings_in_payload(tmp_path):
    """Settings declared in YAML appear in the manifest payload."""
    extra = (
        "settings:\n"
        "  - key: FOO_URL\n"
        "    type: string\n"
        '    label: "Foo URL"\n'
        "  - key: FOO_API_KEY\n"
        "    type: string\n"
        '    label: "Foo API key"\n'
        "    required: true\n"
        "    secret: true\n"
    )
    intg_dir = _make_yaml_integration(tmp_path, "fooarr", extra)
    session = _CapturingSession(existing_row=None)

    with patch(
        "integrations._iter_integration_candidates",
        return_value=[(intg_dir, "fooarr", False, "integration")],
    ), patch(
        "app.db.engine.async_session",
        return_value=session,
    ):
        await seed_manifests()

    stmt = session.executed[0]
    manifest_blob = _insert_values(stmt)["manifest"]
    setting_keys = {s["key"] for s in manifest_blob["settings"]}
    assert "FOO_URL" in setting_keys
    assert "FOO_API_KEY" in setting_keys
