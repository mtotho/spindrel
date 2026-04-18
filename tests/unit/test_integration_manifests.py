"""Tests for app.services.integration_manifests.

Real SQLite-in-memory DB for every code path that opens an ``async_session``.
The module-level ``_manifests`` cache is reset before and after each test by
the autouse ``_reset_manifest_cache`` fixture so tests don't leak state.
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import select

from app.db.models import IntegrationManifest
from app.services import integration_manifests as manifests_mod
from app.services.integration_manifests import (
    _file_hash,
    check_file_drift,
    collect_integration_mcp_servers,
    get_all_manifests,
    get_capabilities,
    get_manifest,
    get_yaml_content,
    load_manifests,
    parse_integration_yaml,
    seed_manifests,
    set_detected_provides,
    update_manifest,
    validate_capabilities,
    validate_provides,
)
from tests.factories import build_integration_manifest


@pytest.fixture(autouse=True)
def _reset_manifest_cache():
    manifests_mod._manifests.clear()
    yield
    manifests_mod._manifests.clear()


# ---------------------------------------------------------------------------
# YAML integration directory helper
# ---------------------------------------------------------------------------

def _write_integration_yaml(tmp_path: Path, integration_id: str, extra: str = "") -> Path:
    intg_dir = tmp_path / integration_id
    intg_dir.mkdir()
    base = textwrap.dedent(f"""\
        id: {integration_id}
        name: {integration_id.replace('_', ' ').title()}
        icon: Plug
        description: "Test integration"
        version: "1.0"
    """)
    (intg_dir / "integration.yaml").write_text(base + extra)
    return intg_dir


# ---------------------------------------------------------------------------
# _file_hash — content drift detection (pure function)
# ---------------------------------------------------------------------------

class TestFileHash:
    def test_when_file_contents_change_then_hash_changes(self, tmp_path):
        f = tmp_path / "integration.yaml"
        f.write_text("id: foo\nname: Foo\n")
        h1 = _file_hash(f)

        f.write_text("id: foo\nname: Foo\nsettings: []\n")
        h2 = _file_hash(f)

        assert h1 != h2

    def test_when_file_unchanged_then_hash_stable(self, tmp_path):
        f = tmp_path / "integration.yaml"
        f.write_text("id: foo\n")
        assert _file_hash(f) == _file_hash(f)


# ---------------------------------------------------------------------------
# parse_integration_yaml — pure validator
# ---------------------------------------------------------------------------

class TestParseIntegrationYaml:
    def test_when_yaml_valid_then_returns_dict(self, tmp_path):
        p = tmp_path / "integration.yaml"
        p.write_text("id: foo\nname: Foo Integration\n")

        data = parse_integration_yaml(p)

        assert data == {"id": "foo", "name": "Foo Integration"}

    def test_when_name_missing_then_auto_inferred_from_id(self, tmp_path):
        p = tmp_path / "integration.yaml"
        p.write_text("id: foo_bar\n")

        data = parse_integration_yaml(p)

        assert data["name"] == "Foo Bar"

    def test_when_id_missing_then_raises(self, tmp_path):
        p = tmp_path / "integration.yaml"
        p.write_text("name: Orphan\n")

        with pytest.raises(ValueError, match="missing required 'id'"):
            parse_integration_yaml(p)

    def test_when_empty_then_raises(self, tmp_path):
        p = tmp_path / "integration.yaml"
        p.write_text("")

        with pytest.raises(ValueError, match="empty or not a mapping"):
            parse_integration_yaml(p)

    def test_when_unknown_keys_then_warned_but_preserved(self, tmp_path, caplog):
        p = tmp_path / "integration.yaml"
        p.write_text("id: foo\nname: Foo\nunknown_key: keep_me\n")
        caplog.set_level(logging.WARNING, logger="app.services.integration_manifests")

        data = parse_integration_yaml(p)

        assert data["unknown_key"] == "keep_me"
        assert any("unknown_key" in r.message for r in caplog.records)

    def test_when_key_starts_with_underscore_then_not_warned(self, tmp_path, caplog):
        p = tmp_path / "integration.yaml"
        p.write_text("id: foo\nname: Foo\n_anchor_target: {}\n")
        caplog.set_level(logging.WARNING, logger="app.services.integration_manifests")

        parse_integration_yaml(p)

        assert not any("_anchor_target" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# seed_manifests — real DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSeedManifests:
    async def test_when_new_yaml_found_then_row_inserted(
        self, tmp_path, db_session, patched_async_sessions, monkeypatch,
    ):
        intg_dir = _write_integration_yaml(tmp_path, "fooarr")
        monkeypatch.setattr(
            "integrations._iter_integration_candidates",
            lambda: [(intg_dir, "fooarr", False, "integration")],
        )

        await seed_manifests()

        row = await db_session.get(IntegrationManifest, "fooarr")
        assert row is not None
        assert row.name == "Fooarr"
        assert row.source == "yaml"
        assert row.content_hash == _file_hash(intg_dir / "integration.yaml")

    async def test_when_yaml_changed_then_row_updated_in_place(
        self, tmp_path, db_session, patched_async_sessions, monkeypatch,
    ):
        intg_dir = _write_integration_yaml(tmp_path, "fooarr")
        db_session.add(build_integration_manifest(
            "fooarr",
            name="Stale Name",
            content_hash="stale-hash",
        ))
        await db_session.commit()
        monkeypatch.setattr(
            "integrations._iter_integration_candidates",
            lambda: [(intg_dir, "fooarr", False, "integration")],
        )

        await seed_manifests()

        await db_session.refresh(await db_session.get(IntegrationManifest, "fooarr"))
        row = await db_session.get(IntegrationManifest, "fooarr")
        assert row.name == "Fooarr"
        assert row.content_hash == _file_hash(intg_dir / "integration.yaml")
        assert row.manifest["description"] == "Test integration"

    async def test_when_yaml_unchanged_then_row_untouched(
        self, tmp_path, db_session, patched_async_sessions, monkeypatch,
    ):
        intg_dir = _write_integration_yaml(tmp_path, "fooarr")
        current_hash = _file_hash(intg_dir / "integration.yaml")
        db_session.add(build_integration_manifest(
            "fooarr",
            name="Already Seeded",
            content_hash=current_hash,
        ))
        await db_session.commit()
        monkeypatch.setattr(
            "integrations._iter_integration_candidates",
            lambda: [(intg_dir, "fooarr", False, "integration")],
        )

        await seed_manifests()

        row = await db_session.get(IntegrationManifest, "fooarr")
        assert row.name == "Already Seeded"
        assert row.content_hash == current_hash

    async def test_when_dir_has_no_yaml_then_skipped(
        self, tmp_path, db_session, patched_async_sessions, monkeypatch,
    ):
        intg_dir = tmp_path / "barint"
        intg_dir.mkdir()
        monkeypatch.setattr(
            "integrations._iter_integration_candidates",
            lambda: [(intg_dir, "barint", False, "integration")],
        )

        await seed_manifests()

        rows = (await db_session.execute(select(IntegrationManifest))).scalars().all()
        assert rows == []

    async def test_when_multiple_yamls_then_all_seeded_and_siblings_isolated(
        self, tmp_path, db_session, patched_async_sessions, monkeypatch,
    ):
        foo_dir = _write_integration_yaml(tmp_path, "fooarr")
        bar_dir = _write_integration_yaml(
            tmp_path, "barint", extra="enabled: true\n",
        )
        monkeypatch.setattr(
            "integrations._iter_integration_candidates",
            lambda: [
                (foo_dir, "fooarr", False, "integration"),
                (bar_dir, "barint", False, "integration"),
            ],
        )

        await seed_manifests()

        ids = {
            r.id: r.is_enabled
            for r in (await db_session.execute(select(IntegrationManifest))).scalars().all()
        }
        assert ids == {"fooarr": False, "barint": True}


# ---------------------------------------------------------------------------
# load_manifests — real DB → in-memory cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestLoadManifests:
    async def test_when_rows_present_then_cache_populated(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest(
            "slack",
            name="Slack",
            icon="Chat",
            manifest={"id": "slack", "name": "Slack", "icon": "Chat", "capabilities": ["EPHEMERAL"]},
        ))
        db_session.add(build_integration_manifest("github", name="GitHub"))
        await db_session.commit()

        await load_manifests()

        assert set(manifests_mod._manifests.keys()) == {"slack", "github"}
        cached = manifests_mod._manifests["slack"]
        assert cached["icon"] == "Chat"
        assert cached["capabilities"] == ["EPHEMERAL"]

    async def test_when_called_twice_then_cache_cleared_between_loads(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest("slack"))
        await db_session.commit()
        await load_manifests()
        # Delete the row and reload — the stale "slack" entry must be gone.
        await db_session.delete(await db_session.get(IntegrationManifest, "slack"))
        await db_session.commit()

        await load_manifests()

        assert manifests_mod._manifests == {}

    async def test_when_manifest_blob_shadows_internal_fields_then_row_wins(
        self, db_session, patched_async_sessions,
    ):
        """If a stored manifest JSONB blob contains keys that collide with the
        row's trusted columns (``content_hash``, ``source``, ``source_path``,
        ``is_enabled``), the row columns must win in the cache. Regression for
        the ``**(row.manifest or {})``-spread-last bug.
        """
        poisoned_blob = {
            "id": "slack",
            "name": "Slack",
            "content_hash": "blob-says-fake",
            "source": "external",
            "source_path": "/tmp/evil.yaml",
            "is_enabled": False,
        }
        db_session.add(build_integration_manifest(
            "slack",
            manifest=poisoned_blob,
            content_hash="real-hash",
            source="yaml",
            source_path="/real/path.yaml",
            is_enabled=True,
        ))
        await db_session.commit()

        await load_manifests()

        cached = manifests_mod._manifests["slack"]
        assert cached["content_hash"] == "real-hash"
        assert cached["source"] == "yaml"
        assert cached["source_path"] == "/real/path.yaml"
        assert cached["is_enabled"] is True


# ---------------------------------------------------------------------------
# update_manifest — real DB + cache refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestUpdateManifest:
    async def test_when_yaml_valid_then_row_and_cache_updated(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest(
            "slack",
            name="Old Slack",
            manifest={"id": "slack", "name": "Old Slack"},
            yaml_content="id: slack\nname: Old Slack\n",
        ))
        await db_session.commit()
        new_yaml = "id: slack\nname: New Slack\ndescription: Edited via UI\n"

        result = await update_manifest("slack", new_yaml)

        assert result["name"] == "New Slack"
        assert result["description"] == "Edited via UI"
        row = await db_session.get(IntegrationManifest, "slack")
        await db_session.refresh(row)
        assert row.name == "New Slack"
        assert row.yaml_content == new_yaml
        assert row.manifest["description"] == "Edited via UI"

    async def test_when_integration_missing_then_raises_value_error(
        self, db_session, patched_async_sessions,
    ):
        with pytest.raises(ValueError, match="Integration 'ghost' not found"):
            await update_manifest("ghost", "id: ghost\nname: Ghost\n")

    async def test_when_yaml_empty_then_raises_value_error(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest("slack"))
        await db_session.commit()

        with pytest.raises(ValueError, match="empty or not a mapping"):
            await update_manifest("slack", "")

    async def test_when_yaml_is_list_then_raises_value_error(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest("slack"))
        await db_session.commit()

        with pytest.raises(ValueError, match="empty or not a mapping"):
            await update_manifest("slack", "- a\n- b\n")

    async def test_when_yaml_id_conflicts_with_path_then_path_wins(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest("slack"))
        await db_session.commit()
        # User tries to rename by editing `id:` — the path arg must override.
        new_yaml = "id: evil_spoof\nname: Slack\n"

        result = await update_manifest("slack", new_yaml)

        assert result["id"] == "slack"
        assert "evil_spoof" not in manifests_mod._manifests
        assert (await db_session.get(IntegrationManifest, "evil_spoof")) is None

    async def test_when_update_succeeds_then_siblings_untouched(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest("slack", name="Slack"))
        db_session.add(build_integration_manifest("github", name="GitHub"))
        await db_session.commit()

        await update_manifest("slack", "id: slack\nname: Renamed Slack\n")

        github = await db_session.get(IntegrationManifest, "github")
        await db_session.refresh(github)
        assert github.name == "GitHub"

    async def test_when_yaml_contains_internal_fields_then_cache_ignores_them(
        self, db_session, patched_async_sessions,
    ):
        """YAML-pasted values for internal metadata (``content_hash``, ``source``,
        ``source_path``, ``is_enabled``) must not override the DB-captured values
        in the in-memory cache. Regression for the ``**data``-spread-last bug
        where user YAML corrupted drift detection.
        """
        db_session.add(build_integration_manifest(
            "slack",
            content_hash="real-hash-from-seed",
            source="yaml",
            source_path="/real/slack/integration.yaml",
            is_enabled=True,
        ))
        await db_session.commit()
        malicious_yaml = textwrap.dedent("""\
            id: slack
            name: Slack
            content_hash: user-pasted-fake-hash
            source: external
            source_path: /tmp/etc/passwd
            is_enabled: false
        """)

        cached = await update_manifest("slack", malicious_yaml)

        assert cached["content_hash"] == "real-hash-from-seed"
        assert cached["source"] == "yaml"
        assert cached["source_path"] == "/real/slack/integration.yaml"
        assert cached["is_enabled"] is True


# ---------------------------------------------------------------------------
# get_yaml_content — real DB read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetYamlContent:
    async def test_when_row_exists_then_returns_yaml(
        self, db_session, patched_async_sessions,
    ):
        db_session.add(build_integration_manifest(
            "slack", yaml_content="id: slack\nname: Slack\n",
        ))
        await db_session.commit()

        result = await get_yaml_content("slack")

        assert result == "id: slack\nname: Slack\n"

    async def test_when_row_missing_then_returns_none(
        self, db_session, patched_async_sessions,
    ):
        result = await get_yaml_content("ghost")

        assert result is None


# ---------------------------------------------------------------------------
# get_manifest / get_all_manifests — cache-only readers
# ---------------------------------------------------------------------------

class TestGetManifest:
    def test_when_id_cached_then_returns_manifest(self):
        manifests_mod._manifests["slack"] = {"id": "slack", "name": "Slack"}

        assert get_manifest("slack") == {"id": "slack", "name": "Slack"}

    def test_when_id_missing_then_returns_none(self):
        assert get_manifest("ghost") is None


class TestGetAllManifests:
    def test_when_cache_populated_then_returns_copy(self):
        manifests_mod._manifests["slack"] = {"id": "slack"}
        manifests_mod._manifests["github"] = {"id": "github"}

        snapshot = get_all_manifests()
        snapshot["slack"] = {"id": "mutated"}

        assert manifests_mod._manifests["slack"] == {"id": "slack"}

    def test_when_cache_empty_then_returns_empty_dict(self):
        assert get_all_manifests() == {}


# ---------------------------------------------------------------------------
# get_capabilities — cache-based
# ---------------------------------------------------------------------------

class TestGetCapabilities:
    def test_when_capabilities_declared_then_frozenset_returned(self):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "capabilities": ["EPHEMERAL", "MODALS"],
        }

        result = get_capabilities("slack")

        assert result == frozenset({"EPHEMERAL", "MODALS"})

    def test_when_capabilities_missing_then_none(self):
        manifests_mod._manifests["slack"] = {"id": "slack"}

        assert get_capabilities("slack") is None

    def test_when_integration_missing_then_none(self):
        assert get_capabilities("ghost") is None


# ---------------------------------------------------------------------------
# set_detected_provides — cache mutator
# ---------------------------------------------------------------------------

class TestSetDetectedProvides:
    def test_when_id_cached_then_detected_persisted_sorted(self):
        manifests_mod._manifests["slack"] = {"id": "slack"}

        set_detected_provides("slack", {"hooks", "skills", "carapaces"})

        assert manifests_mod._manifests["slack"]["_detected_provides"] == [
            "carapaces", "hooks", "skills",
        ]

    def test_when_id_missing_then_silent_noop(self):
        set_detected_provides("ghost", {"hooks"})

        assert "ghost" not in manifests_mod._manifests

    def test_when_called_twice_then_overwrites_previous_value(self):
        manifests_mod._manifests["slack"] = {"id": "slack"}
        set_detected_provides("slack", {"hooks"})

        set_detected_provides("slack", {"skills"})

        assert manifests_mod._manifests["slack"]["_detected_provides"] == ["skills"]


# ---------------------------------------------------------------------------
# check_file_drift — tmp_path + cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckFileDrift:
    async def test_when_disk_hash_matches_stored_then_returns_none(self, tmp_path):
        p = tmp_path / "integration.yaml"
        p.write_text("id: slack\nname: Slack\n")
        disk_hash = _file_hash(p)
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "source": "yaml",
            "source_path": str(p),
            "content_hash": disk_hash,
        }

        assert await check_file_drift("slack") is None

    async def test_when_disk_hash_differs_then_reports_drift(self, tmp_path):
        p = tmp_path / "integration.yaml"
        p.write_text("id: slack\nname: Slack\n")
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "source": "yaml",
            "source_path": str(p),
            "content_hash": "stale-hash-from-prior-seed",
        }

        result = await check_file_drift("slack")

        assert result == {
            "drifted": True,
            "disk_hash": _file_hash(p),
            "reason": "content_changed",
        }

    async def test_when_file_missing_then_reports_file_missing(self, tmp_path):
        missing = tmp_path / "gone.yaml"
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "source": "yaml",
            "source_path": str(missing),
            "content_hash": "any",
        }

        result = await check_file_drift("slack")

        assert result == {"drifted": True, "disk_hash": None, "reason": "file_missing"}

    async def test_when_integration_missing_then_returns_none(self):
        assert await check_file_drift("ghost") is None

    async def test_when_source_not_yaml_then_returns_none(self, tmp_path):
        p = tmp_path / "integration.yaml"
        p.write_text("id: slack\n")
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "source": "package",
            "source_path": str(p),
            "content_hash": "whatever",
        }

        assert await check_file_drift("slack") is None


# ---------------------------------------------------------------------------
# collect_integration_mcp_servers — pure function over cache
# ---------------------------------------------------------------------------

class TestCollectIntegrationMcpServers:
    def test_when_activated_integrations_declare_servers_then_deduplicated(self):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "mcp_servers": [{"id": "shared"}, {"id": "slack-only"}],
        }
        manifests_mod._manifests["github"] = {
            "id": "github",
            "mcp_servers": [{"id": "shared"}, {"id": "github-only"}],
        }
        channel_integrations = [
            SimpleNamespace(activated=True, integration_type="slack"),
            SimpleNamespace(activated=True, integration_type="github"),
        ]

        result = collect_integration_mcp_servers(channel_integrations)

        assert result == ["shared", "slack-only", "github-only"]

    def test_when_integration_not_activated_then_ignored(self):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "mcp_servers": [{"id": "slack-only"}],
        }
        channel_integrations = [
            SimpleNamespace(activated=False, integration_type="slack"),
        ]

        assert collect_integration_mcp_servers(channel_integrations) == []

    def test_when_exclude_provided_then_servers_filtered(self):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "mcp_servers": [{"id": "shared"}, {"id": "slack-only"}],
        }
        channel_integrations = [
            SimpleNamespace(activated=True, integration_type="slack"),
        ]

        result = collect_integration_mcp_servers(channel_integrations, exclude={"shared"})

        assert result == ["slack-only"]


# ---------------------------------------------------------------------------
# validate_capabilities / validate_provides — cache + caplog
# ---------------------------------------------------------------------------

class TestValidateCapabilities:
    def test_when_unknown_capability_then_warning_logged(self, caplog):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "capabilities": ["EPHEMERAL", "UNKNOWN_CAP"],
        }
        caplog.set_level(logging.WARNING, logger="app.services.integration_manifests")

        validate_capabilities()

        assert any("UNKNOWN_CAP" in r.message for r in caplog.records)

    def test_when_all_capabilities_valid_then_silent(self, caplog):
        from app.domain.capability import Capability
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "capabilities": [next(iter(Capability)).value],
        }
        caplog.set_level(logging.WARNING, logger="app.services.integration_manifests")

        validate_capabilities()

        assert not any(
            "unknown capabilities" in r.message for r in caplog.records
        )


class TestValidateProvides:
    def test_when_declared_missing_then_warning_logged(self, caplog):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "provides": ["hooks", "skills"],
            "_detected_provides": ["hooks"],
        }
        caplog.set_level(logging.WARNING, logger="app.services.integration_manifests")

        validate_provides()

        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("skills" in m for m in warn_msgs)

    def test_when_detected_extra_then_info_logged(self, caplog):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "provides": ["hooks"],
            "_detected_provides": ["hooks", "skills"],
        }
        caplog.set_level(logging.INFO, logger="app.services.integration_manifests")

        validate_provides()

        info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("undeclared modules" in m and "skills" in m for m in info_msgs)

    def test_when_no_provides_declared_then_silent(self, caplog):
        manifests_mod._manifests["slack"] = {
            "id": "slack",
            "_detected_provides": ["hooks"],
        }
        caplog.set_level(logging.INFO, logger="app.services.integration_manifests")

        validate_provides()

        assert not any(
            "undeclared modules" in r.message or "modules not found" in r.message
            for r in caplog.records
        )
