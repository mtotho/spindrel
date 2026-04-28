"""Pin contract drift scanner script tests.

The script name is retained for operators, but Phase 4 changed the behavior
from stamp-only backfill to full pin contract drift scan/repair.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WidgetDashboardPin
from app.services.pin_contract import compute_pin_metadata


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


def _current_native_pin_kwargs(**overrides: Any) -> dict[str, Any]:
    base = _native_pin_kwargs()
    view, stamp = compute_pin_metadata(
        tool_name=base["tool_name"],
        envelope=base["envelope"],
        source_bot_id=base["source_bot_id"],
        caller_origin=base["widget_origin"],
    )
    base.update(
        widget_origin=view.widget_origin,
        provenance_confidence=view.provenance_confidence,
        widget_contract_snapshot=view.widget_contract,
        config_schema_snapshot=view.config_schema,
        widget_presentation_snapshot=view.widget_presentation,
        source_stamp=stamp,
    )
    base.update(overrides)
    return base


@pytest.fixture
def patched_async_session(engine):
    """Point the script's ``async_session`` at the test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(backfill_mod, "async_session", factory):
        yield factory


@pytest.mark.asyncio
async def test_scan_reports_null_stamp_and_snapshot_drift(
    patched_async_session,
    db_session,
):
    pin = WidgetDashboardPin(**_native_pin_kwargs())
    db_session.add(pin)
    await db_session.commit()

    result = await backfill_mod.scan(
        batch_size=100,
        dashboard_key=None,
        limit=None,
        repair=False,
    )

    assert result["stats"]["scanned"] >= 1
    assert result["stats"]["drifted"] == 1
    assert result["stats"]["drift.source_stamp"] == 1
    assert result["drifts"][0]["pin_id"] == str(pin.id)


@pytest.mark.asyncio
async def test_repair_writes_stamp_and_snapshots(patched_async_session, db_session):
    pin = WidgetDashboardPin(**_native_pin_kwargs(widget_contract_snapshot={"stale": True}))
    db_session.add(pin)
    await db_session.commit()
    pin_id = pin.id

    result = await backfill_mod.scan(
        batch_size=100,
        dashboard_key=None,
        limit=None,
        repair=True,
    )
    assert result["stats"]["repaired"] == 1

    factory = patched_async_session
    async with factory() as fresh:
        row = (await fresh.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()
        assert row.source_stamp is not None
        assert row.widget_contract_snapshot["definition_kind"] == "native_widget"
        assert row.widget_presentation_snapshot["presentation_family"] == "card"


@pytest.mark.asyncio
async def test_current_row_is_clean(patched_async_session, db_session):
    pin = WidgetDashboardPin(**_current_native_pin_kwargs())
    db_session.add(pin)
    await db_session.commit()

    result = await backfill_mod.verify(
        batch_size=100,
        dashboard_key=None,
        limit=None,
    )

    assert result["stats"]["clean"] == 1
    assert result["stats"].get("drifted", 0) == 0
    assert result["drifts"] == []


@pytest.mark.asyncio
async def test_repair_filter_by_dashboard_key(patched_async_session, db_session):
    pin = WidgetDashboardPin(**_native_pin_kwargs(dashboard_key="default"))
    db_session.add(pin)
    await db_session.commit()

    result = await backfill_mod.scan(
        batch_size=100,
        dashboard_key="never-matches",
        limit=None,
        repair=True,
    )

    assert result["stats"].get("scanned", 0) == 0


@pytest.mark.asyncio
async def test_compat_backfill_wrapper_repairs_when_not_dry_run(
    patched_async_session,
    db_session,
):
    pin = WidgetDashboardPin(**_native_pin_kwargs())
    db_session.add(pin)
    await db_session.commit()
    pin_id = pin.id

    stats = await backfill_mod.backfill(
        batch_size=100,
        dashboard_key=None,
        dry_run=False,
    )
    assert stats["repaired"] == 1

    factory = patched_async_session
    async with factory() as fresh:
        row = (await fresh.execute(
            select(WidgetDashboardPin).where(WidgetDashboardPin.id == pin_id)
        )).scalar_one()
        assert row.source_stamp is not None
