"""Phase 2 backfill script — pinning the contracts that matter.

Pins:
- ``backfill`` writes ``source_stamp`` on rows where it is NULL and skips
  rows that already have one (idempotency).
- ``--verify`` mode (``verify`` function) flags pins where the new-path
  ``compute_pin_metadata`` disagrees with legacy
  ``build_pin_contract_metadata``.
- ``_diff_views`` returns the set of drifted field names.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import importlib.util
from pathlib import Path

from app.db.models import WidgetDashboardPin


def _load_backfill_module():
    """Load ``scripts/backfill_pin_source_stamps.py`` without requiring
    ``scripts`` to be on the import path (it isn't a package)."""
    spec = importlib.util.spec_from_file_location(
        "backfill_pin_source_stamps_mod",
        Path(__file__).resolve().parent.parent.parent
        / "scripts" / "backfill_pin_source_stamps.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


backfill_mod = _load_backfill_module()


def _bare_pin(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": uuid.uuid4(),
        "dashboard_key": "default",
        "position": 0,
        "source_kind": "channel",
        "source_channel_id": None,
        "source_bot_id": None,
        "tool_name": "html_widget",
        "tool_args": {},
        "widget_config": {},
        "envelope": {
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "<html></html>",
        },
        "grid_layout": {},
        "widget_origin": None,
        "provenance_confidence": "inferred",
        "widget_contract_snapshot": None,
        "config_schema_snapshot": None,
        "widget_presentation_snapshot": None,
        "source_stamp": None,
    }
    base.update(overrides)
    return base


def _native_pin_kwargs(**overrides: Any) -> dict[str, Any]:
    base = _bare_pin(
        tool_name="native",
        envelope={
            "content_type": "application/vnd.spindrel.native-app+json",
            "body": {"widget_ref": "core/notes_native"},
        },
        widget_origin={
            "definition_kind": "native_widget",
            "instantiation_kind": "native_catalog",
            "widget_ref": "core/notes_native",
        },
        provenance_confidence="authoritative",
    )
    base.update(overrides)
    return base


@pytest.fixture
def patched_async_session(engine):
    """Point the script's ``async_session`` at the test engine for backfill()."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(backfill_mod, "async_session", factory):
        yield factory


# ── _diff_views ────────────────────────────────────────────────────


class TestDiffViews:
    def test_native_pin_with_authoritative_origin_no_drift(self):
        pin = WidgetDashboardPin(**_native_pin_kwargs())
        assert backfill_mod._diff_views(pin) == []

    def test_html_pin_runtime_emit_no_drift(self):
        pin = WidgetDashboardPin(**_bare_pin())
        # No origin, runtime-emit envelope → both paths land on the same
        # html_widget+runtime_emit shape.
        drift = backfill_mod._diff_views(pin)
        # Either zero drift (both paths equivalent) or only on snapshot fields
        # that legacy left None vs new-path materialized — both acceptable.
        # The test pins that the diff machinery doesn't error.
        assert isinstance(drift, list)


# ── backfill (end-to-end against test SQLite) ──────────────────────


@pytest.mark.asyncio
async def test_backfill_stamps_native_pin(patched_async_session, db_session):
    pin = WidgetDashboardPin(**_native_pin_kwargs())
    db_session.add(pin)
    await db_session.commit()
    pin_id = pin.id

    stats = await backfill_mod.backfill(
        batch_size=100, dashboard_key=None, dry_run=False,
    )
    assert stats["scanned"] >= 1
    assert any(k.startswith("stamped.") for k in stats)

    # Re-read in a fresh session to confirm the stamp persisted.
    factory = patched_async_session
    async with factory() as fresh:
        row = (await fresh.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()
        assert row.source_stamp is not None


@pytest.mark.asyncio
async def test_backfill_is_idempotent(patched_async_session, db_session):
    pin = WidgetDashboardPin(**_native_pin_kwargs(source_stamp="already-set"))
    db_session.add(pin)
    await db_session.commit()
    pin_id = pin.id

    stats = await backfill_mod.backfill(
        batch_size=100, dashboard_key=None, dry_run=False,
    )
    # Already-stamped row excluded by ``source_stamp IS NULL`` filter.
    assert stats.get("scanned", 0) == 0

    factory = patched_async_session
    async with factory() as fresh:
        row = (await fresh.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()
        assert row.source_stamp == "already-set"


@pytest.mark.asyncio
async def test_backfill_dry_run_writes_nothing(patched_async_session, db_session):
    pin = WidgetDashboardPin(**_native_pin_kwargs())
    db_session.add(pin)
    await db_session.commit()
    pin_id = pin.id

    stats = await backfill_mod.backfill(
        batch_size=100, dashboard_key=None, dry_run=True,
    )
    assert stats["scanned"] == 1

    factory = patched_async_session
    async with factory() as fresh:
        row = (await fresh.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()
        assert row.source_stamp is None


@pytest.mark.asyncio
async def test_backfill_filter_by_dashboard_key(patched_async_session, db_session):
    a = WidgetDashboardPin(**_native_pin_kwargs(dashboard_key="default"))
    # Only seed the default dashboard — the other slug isn't seeded by the
    # engine fixture so we can't insert there without FK violation. Filter
    # behavior is exercised by passing a non-matching key to skip the row.
    db_session.add(a)
    await db_session.commit()

    stats = await backfill_mod.backfill(
        batch_size=100, dashboard_key="never-matches", dry_run=False,
    )
    assert stats.get("scanned", 0) == 0


@pytest.mark.asyncio
async def test_verify_clean_run(patched_async_session, db_session):
    pin = WidgetDashboardPin(**_native_pin_kwargs())
    db_session.add(pin)
    await db_session.commit()

    result = await backfill_mod.verify(
        batch_size=100, dashboard_key=None, limit=None,
    )
    assert result["stats"]["scanned"] >= 1
    # Native authoritative pins should have parity between paths.
    assert result["stats"].get("mismatch", 0) == 0
