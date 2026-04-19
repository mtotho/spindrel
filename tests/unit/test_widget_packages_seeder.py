"""Unit tests for app/services/widget_packages_seeder.py.

Tests the idempotency, orphan sweep, and sample-payload sync contracts.
All tests use the real SQLite-in-memory DB via db_session / patched_async_sessions.
_collect_sources is mocked so no integration manifests or filesystem are needed.
"""
from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
import yaml
from sqlalchemy import select

from app.db.models import WidgetTemplatePackage
from app.services.widget_packages_seeder import (
    _dump_yaml,
    _hash_yaml,
    seed_widget_packages,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _widget_def(tool_name: str = "my_tool", extra: dict | None = None) -> dict:
    """Minimal valid widget definition."""
    d: dict = {"template": {"v": 1, "components": []}}
    if extra:
        d.update(extra)
    return d


def _source(
    tool_name: str = "my_tool",
    widget_def: dict | None = None,
    source_file: str | None = "core.widgets.yaml",
    source_integration: str | None = None,
) -> tuple:
    return (tool_name, widget_def or _widget_def(tool_name), source_file, source_integration)


async def _all_packages(db_session) -> list[WidgetTemplatePackage]:
    result = await db_session.execute(select(WidgetTemplatePackage))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# M.8 — Initial insert contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initial_insert_creates_seed_row(db_session, patched_async_sessions):
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source()]):
        await seed_widget_packages()

    pkgs = await _all_packages(db_session)
    assert len(pkgs) == 1
    pkg = pkgs[0]
    assert pkg.tool_name == "my_tool"
    assert pkg.source == "seed"
    assert pkg.is_readonly is True
    assert pkg.is_orphaned is False
    assert pkg.content_hash is not None


@pytest.mark.asyncio
async def test_first_seed_for_tool_is_active(db_session, patched_async_sessions):
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source()]):
        await seed_widget_packages()

    pkg = (await _all_packages(db_session))[0]
    assert pkg.is_active is True


@pytest.mark.asyncio
async def test_second_seed_same_tool_different_file_is_inactive(db_session, patched_async_sessions):
    sources = [
        _source("my_tool", source_file="file_a.yaml"),
        _source("my_tool", source_file="file_b.yaml"),
    ]
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=sources):
        await seed_widget_packages()

    pkgs = await _all_packages(db_session)
    assert len(pkgs) == 2
    active = [p for p in pkgs if p.is_active]
    inactive = [p for p in pkgs if not p.is_active]
    assert len(active) == 1
    assert len(inactive) == 1


@pytest.mark.asyncio
async def test_sample_payload_stored_separately(db_session, patched_async_sessions):
    wdef = _widget_def()
    wdef["sample_payload"] = {"status": "on", "entity": "light.kitchen"}
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source(widget_def=wdef)]):
        await seed_widget_packages()

    pkg = (await _all_packages(db_session))[0]
    assert pkg.sample_payload == {"status": "on", "entity": "light.kitchen"}
    # sample_payload must not appear inside yaml_template body
    parsed = yaml.safe_load(pkg.yaml_template)
    assert "sample_payload" not in parsed


# ---------------------------------------------------------------------------
# M.9 — Hash idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rerun_same_content_no_version_bump(db_session, patched_async_sessions):
    src = [_source()]
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=src):
        await seed_widget_packages()
        await seed_widget_packages()

    pkgs = await _all_packages(db_session)
    assert len(pkgs) == 1
    assert pkgs[0].version == 1


@pytest.mark.asyncio
async def test_rerun_changed_content_bumps_version(db_session, patched_async_sessions):
    src_v1 = [_source(widget_def=_widget_def())]
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=src_v1):
        await seed_widget_packages()

    wdef_v2 = _widget_def()
    wdef_v2["display_label"] = "{{entity}}"
    src_v2 = [_source(widget_def=wdef_v2)]
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=src_v2):
        await seed_widget_packages()

    pkgs = await _all_packages(db_session)
    assert len(pkgs) == 1
    assert pkgs[0].version == 2


@pytest.mark.asyncio
async def test_version_bump_clears_is_invalid(db_session, patched_async_sessions):
    src_v1 = [_source()]
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=src_v1):
        await seed_widget_packages()

    # Manually mark as invalid (simulates a previous bad load)
    pkgs = await _all_packages(db_session)
    pkgs[0].is_invalid = True
    pkgs[0].invalid_reason = "Bad schema"
    await db_session.commit()

    wdef_v2 = _widget_def()
    wdef_v2["display_label"] = "{{entity}}"
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source(widget_def=wdef_v2)]):
        await seed_widget_packages()

    await db_session.expire_all()
    pkgs = await _all_packages(db_session)
    assert pkgs[0].is_invalid is False
    assert pkgs[0].invalid_reason is None


# ---------------------------------------------------------------------------
# M.10 — Orphan sweep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_removed_source_marks_row_orphaned(db_session, patched_async_sessions):
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source()]):
        await seed_widget_packages()

    # Second run with no sources → the previously seeded row is orphaned
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[]):
        await seed_widget_packages()

    await db_session.expire_all()
    pkgs = await _all_packages(db_session)
    assert pkgs[0].is_orphaned is True


@pytest.mark.asyncio
async def test_orphaned_active_row_transfers_active_to_replacement(db_session, patched_async_sessions):
    src_a = _source("my_tool", source_file="file_a.yaml")
    src_b = _source("my_tool", source_file="file_b.yaml")

    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[src_a, src_b]):
        await seed_widget_packages()

    # file_a was first → is_active=True. Remove file_a; file_b should become active.
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[src_b]):
        await seed_widget_packages()

    await db_session.expire_all()
    pkgs = await _all_packages(db_session)
    by_file = {p.source_file: p for p in pkgs}

    assert by_file["file_a.yaml"].is_orphaned is True
    assert by_file["file_a.yaml"].is_active is False
    assert by_file["file_b.yaml"].is_active is True


# ---------------------------------------------------------------------------
# M.11 — Un-orphan on re-add
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reappeared_source_clears_orphan_flag(db_session, patched_async_sessions):
    src = [_source()]
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=src):
        await seed_widget_packages()

    # Orphan it
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[]):
        await seed_widget_packages()

    # Re-add the source — orphan flag should be cleared, no duplicate inserted
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=src):
        await seed_widget_packages()

    await db_session.expire_all()
    pkgs = await _all_packages(db_session)
    assert len(pkgs) == 1
    assert pkgs[0].is_orphaned is False


# ---------------------------------------------------------------------------
# M.12 — Sample-payload sync
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sample_payload_updated_on_change_without_version_bump(db_session, patched_async_sessions):
    wdef_v1 = _widget_def()
    wdef_v1["sample_payload"] = {"x": 1}
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source(widget_def=wdef_v1)]):
        await seed_widget_packages()

    pkgs = await _all_packages(db_session)
    assert pkgs[0].version == 1
    assert pkgs[0].sample_payload == {"x": 1}

    # Change only the sample_payload (YAML body unchanged → hash unchanged)
    wdef_v2 = _widget_def()
    wdef_v2["sample_payload"] = {"x": 99}
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source(widget_def=wdef_v2)]):
        await seed_widget_packages()

    await db_session.expire_all()
    pkgs = await _all_packages(db_session)
    assert pkgs[0].sample_payload == {"x": 99}
    # Version unchanged because the yaml_template body (after stripping sample_payload) is identical
    assert pkgs[0].version == 1


@pytest.mark.asyncio
async def test_no_sample_payload_in_source_does_not_overwrite_existing(db_session, patched_async_sessions):
    wdef_v1 = _widget_def()
    wdef_v1["sample_payload"] = {"x": 1}
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source(widget_def=wdef_v1)]):
        await seed_widget_packages()

    # Second run with no sample_payload in YAML — existing payload preserved
    with patch("app.services.widget_packages_seeder._collect_sources", return_value=[_source()]):
        await seed_widget_packages()

    await db_session.expire_all()
    pkgs = await _all_packages(db_session)
    assert pkgs[0].sample_payload == {"x": 1}


# ---------------------------------------------------------------------------
# _hash_yaml / _dump_yaml unit tests (pure)
# ---------------------------------------------------------------------------

def test_hash_yaml_is_deterministic():
    body = "template:\n  v: 1\n"
    assert _hash_yaml(body) == _hash_yaml(body)


def test_hash_yaml_differs_for_different_content():
    assert _hash_yaml("a") != _hash_yaml("b")


def test_dump_yaml_round_trips():
    d = {"template": {"v": 1, "components": []}, "display_label": "{{state}}"}
    body = _dump_yaml(d)
    parsed = yaml.safe_load(body)
    assert parsed == d
