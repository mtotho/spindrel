"""Tests for app.services.integration_manifests.

Focus: setup.py manifests must re-sync to the DB on every startup when the
file changes. The previous implementation used INSERT ON CONFLICT DO NOTHING
which silently dropped any setup.py edits — adding a new env_var to a legacy
integration's setup.py would never reach the admin UI without a manual DB
DELETE. Regression coverage for the FlareSolverr URL incident (2026-04-11).
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects.postgresql import Insert as PgInsert

from app.services.integration_manifests import (
    _file_hash,
    seed_manifests,
    setup_dict_to_manifest,
)


# ---------------------------------------------------------------------------
# setup_dict_to_manifest — pure conversion
# ---------------------------------------------------------------------------


class TestSetupDictToManifest:
    def test_env_vars_become_settings(self):
        setup = {
            "icon": "Tv",
            "env_vars": [
                {"key": "FOO_URL", "required": False, "description": "Foo base URL"},
                {"key": "FOO_API_KEY", "required": True, "description": "Foo API key", "secret": True},
            ],
        }
        manifest = setup_dict_to_manifest("foo", setup)

        assert manifest["id"] == "foo"
        assert manifest["icon"] == "Tv"
        assert len(manifest["settings"]) == 2

        url = manifest["settings"][0]
        assert url["key"] == "FOO_URL"
        assert url["required"] is False
        assert url["secret"] is False
        assert url["label"] == "Foo base URL"

        api_key = manifest["settings"][1]
        assert api_key["key"] == "FOO_API_KEY"
        assert api_key["required"] is True
        assert api_key["secret"] is True

    def test_env_var_added_changes_manifest_settings(self):
        """Smoke test for the FlareSolverr regression: adding a new env_var
        to setup.py must produce a manifest with that key in settings."""
        before = {"env_vars": [{"key": "A_URL"}, {"key": "B_URL"}]}
        after = {"env_vars": [{"key": "A_URL"}, {"key": "B_URL"}, {"key": "C_URL"}]}

        before_settings = {s["key"] for s in setup_dict_to_manifest("x", before)["settings"]}
        after_settings = {s["key"] for s in setup_dict_to_manifest("x", after)["settings"]}

        assert "C_URL" not in before_settings
        assert "C_URL" in after_settings

    def test_passthrough_keys_preserved(self):
        setup = {
            "env_vars": [],
            "activation": {"carapaces": ["foo"]},
            "webhook": {"path": "/foo"},
        }
        manifest = setup_dict_to_manifest("foo", setup)
        assert manifest["activation"] == {"carapaces": ["foo"]}
        assert manifest["webhook"] == {"path": "/foo"}


# ---------------------------------------------------------------------------
# _file_hash — content drift detection
# ---------------------------------------------------------------------------


class TestFileHash:
    def test_hash_changes_when_file_changes(self, tmp_path):
        f = tmp_path / "setup.py"
        f.write_text("SETUP = {'env_vars': [{'key': 'A_URL'}]}\n")
        h1 = _file_hash(f)

        f.write_text("SETUP = {'env_vars': [{'key': 'A_URL'}, {'key': 'B_URL'}]}\n")
        h2 = _file_hash(f)

        assert h1 != h2

    def test_hash_stable_when_file_unchanged(self, tmp_path):
        f = tmp_path / "setup.py"
        f.write_text("SETUP = {}\n")
        assert _file_hash(f) == _file_hash(f)


# ---------------------------------------------------------------------------
# seed_manifests — setup.py upsert behavior
# ---------------------------------------------------------------------------


def _insert_values(stmt) -> dict:
    """Extract a {column_name: python_value} dict from a pg_insert statement.

    pg_insert stores its .values() under ._values keyed by Column objects;
    each value is a BindParameter with a .value attribute.
    """
    return {col.name: bind.value for col, bind in stmt._values.items()}


def _make_setup_py(tmp_path: Path, integration_id: str, env_var_keys: list[str]) -> Path:
    """Build a temporary integration directory with a setup.py file."""
    intg_dir = tmp_path / integration_id
    intg_dir.mkdir()
    env_var_lines = ",\n        ".join(
        f"{{'key': '{k}', 'required': False, 'description': '{k} desc'}}"
        for k in env_var_keys
    )
    body = textwrap.dedent(f"""
        SETUP = {{
            "icon": "Tv",
            "env_vars": [
                {env_var_lines}
            ],
        }}
    """)
    (intg_dir / "setup.py").write_text(body)
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
async def test_seed_manifests_first_time_inserts_setup_py_row(tmp_path):
    """First-ever seed for a setup.py integration: INSERT executed with content_hash set."""
    intg_dir = _make_setup_py(tmp_path, "fooarr", ["FOOARR_URL"])
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

    # Inspect the INSERT values via the compiled parameters
    extracted = _insert_values(stmt)
    assert extracted["id"] == "fooarr"
    assert extracted["source"] == "setup_py"
    assert extracted["content_hash"]  # non-empty
    assert "FOOARR_URL" in str(extracted["manifest"])


@pytest.mark.asyncio
async def test_seed_manifests_setup_py_uses_on_conflict_do_update(tmp_path):
    """The upsert statement must be ON CONFLICT DO UPDATE, not DO NOTHING.

    This is the core regression: the old code used .on_conflict_do_nothing()
    which silently dropped any setup.py changes after the first startup.
    """
    intg_dir = _make_setup_py(tmp_path, "fooarr", ["FOOARR_URL"])
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
    # SQLAlchemy stores the conflict clause on the Insert statement
    on_conflict = getattr(stmt, "_post_values_clause", None)
    assert on_conflict is not None, "expected ON CONFLICT clause on the statement"
    # The clause class name distinguishes do_update vs do_nothing
    assert "DoUpdate" in type(on_conflict).__name__, (
        f"expected ON CONFLICT DO UPDATE, got {type(on_conflict).__name__}"
    )


@pytest.mark.asyncio
async def test_seed_manifests_after_setup_py_change_logs_refresh(tmp_path, caplog):
    """When the setup.py content hash differs from the existing row, log a refresh."""
    intg_dir = _make_setup_py(tmp_path, "fooarr", ["FOOARR_URL"])

    # Simulate an existing row whose hash predates the current file
    existing = MagicMock()
    existing.content_hash = "stale-hash-from-prior-startup"
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

    refresh_logs = [r for r in caplog.records if "Refreshed setup.py manifest" in r.message]
    assert len(refresh_logs) == 1
    assert "fooarr" in refresh_logs[0].message


@pytest.mark.asyncio
async def test_seed_manifests_unchanged_setup_py_does_not_log_refresh(tmp_path, caplog):
    """When the setup.py content hash matches the existing row, do not log a refresh."""
    intg_dir = _make_setup_py(tmp_path, "fooarr", ["FOOARR_URL"])
    current_hash = _file_hash(intg_dir / "setup.py")

    existing = MagicMock()
    existing.content_hash = current_hash
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

    refresh_logs = [r for r in caplog.records if "Refreshed setup.py manifest" in r.message]
    assert refresh_logs == []
    seed_logs = [r for r in caplog.records if "Seeded new setup.py manifest" in r.message]
    assert seed_logs == []


@pytest.mark.asyncio
async def test_seed_manifests_setup_py_carries_new_env_var_in_payload(tmp_path):
    """End-to-end smoke test for the FlareSolverr regression: when setup.py
    declares a new env_var, the manifest payload sent to the DB must contain it."""
    intg_dir = _make_setup_py(
        tmp_path, "fooarr", ["FOOARR_URL", "FOOARR_API_KEY", "FLARESOLVERR_URL"]
    )
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
    assert "FLARESOLVERR_URL" in setting_keys
    assert "FOOARR_URL" in setting_keys
    assert "FOOARR_API_KEY" in setting_keys
