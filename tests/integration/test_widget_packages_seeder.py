"""Integration tests for the widget_template_packages seeder and DB resolver."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import WidgetTemplatePackage
from app.services import widget_packages_seeder, widget_templates


@pytest_asyncio.fixture
async def sessionmaker_fixture(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch the engine module's async_session so the seeder picks up the test engine.
    from app.db import engine as engine_mod
    with patch.object(engine_mod, "async_session", factory):
        yield factory


def _make_sources(tools: list[dict]) -> list:
    return [
        (
            t["tool_name"],
            t["widget_def"],
            t.get("source_file"),
            t.get("source_integration"),
        )
        for t in tools
    ]


@pytest.mark.asyncio
async def test_seeds_inserts_and_activates_first_seed(sessionmaker_fixture):
    widget_def = {
        "template": {"v": 1, "components": [{"type": "status", "text": "Hi"}]},
    }
    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": widget_def, "source_integration": "foo"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()

    async with sessionmaker_fixture() as db:
        rows = (await db.execute(select(WidgetTemplatePackage))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.tool_name == "t1"
        assert row.source == "seed"
        assert row.is_readonly is True
        assert row.is_active is True
        assert row.source_integration == "foo"


@pytest.mark.asyncio
async def test_idempotent_no_change(sessionmaker_fixture):
    widget_def = {"template": {"v": 1, "components": []}}
    sources = _make_sources([
        {"tool_name": "t1", "widget_def": widget_def, "source_integration": "foo"},
    ])
    with patch.object(widget_packages_seeder, "_collect_sources", return_value=sources):
        await widget_packages_seeder.seed_widget_packages()
        await widget_packages_seeder.seed_widget_packages()

    async with sessionmaker_fixture() as db:
        rows = (await db.execute(select(WidgetTemplatePackage))).scalars().all()
        assert len(rows) == 1
        assert rows[0].version == 1


@pytest.mark.asyncio
async def test_update_on_content_change_bumps_version(sessionmaker_fixture):
    wd1 = {"template": {"v": 1, "components": [{"type": "status", "text": "a"}]}}
    wd2 = {"template": {"v": 1, "components": [{"type": "status", "text": "b"}]}}

    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": wd1, "source_integration": "foo"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()

    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": wd2, "source_integration": "foo"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()

    async with sessionmaker_fixture() as db:
        row = (await db.execute(select(WidgetTemplatePackage))).scalar_one()
        assert row.version == 2
        assert "text: b" in row.yaml_template


@pytest.mark.asyncio
async def test_user_active_survives_seed_refresh(sessionmaker_fixture):
    wd1 = {"template": {"v": 1, "components": []}}
    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": wd1, "source_integration": "foo"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()

    # Deactivate seed, create+activate a user row.
    async with sessionmaker_fixture() as db:
        seed = (await db.execute(select(WidgetTemplatePackage))).scalar_one()
        seed.is_active = False
        await db.flush()
        user_row = WidgetTemplatePackage(
            tool_name="t1",
            name="User Template",
            yaml_template="template:\n  v: 1\n  components: []\n",
            source="user",
            is_readonly=False,
            is_active=True,
            version=1,
        )
        db.add(user_row)
        await db.commit()

    wd2 = {"template": {"v": 1, "components": [{"type": "status", "text": "new"}]}}
    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": wd2, "source_integration": "foo"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()

    async with sessionmaker_fixture() as db:
        user = (await db.execute(
            select(WidgetTemplatePackage).where(WidgetTemplatePackage.source == "user")
        )).scalar_one()
        seed = (await db.execute(
            select(WidgetTemplatePackage).where(WidgetTemplatePackage.source == "seed")
        )).scalar_one()
        assert user.is_active is True
        assert seed.is_active is False
        assert seed.version == 2


@pytest.mark.asyncio
async def test_orphan_flag_set_when_source_gone(sessionmaker_fixture):
    wd1 = {"template": {"v": 1, "components": []}}
    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": wd1, "source_integration": "gone"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()

    with patch.object(widget_packages_seeder, "_collect_sources", return_value=[]):
        await widget_packages_seeder.seed_widget_packages()

    async with sessionmaker_fixture() as db:
        row = (await db.execute(select(WidgetTemplatePackage))).scalar_one()
        assert row.is_orphaned is True


@pytest.mark.asyncio
async def test_load_from_db_populates_registry(sessionmaker_fixture):
    widget_templates._widget_templates.clear()
    widget_def = {
        "template": {
            "v": 1,
            "components": [{"type": "status", "text": "{{message}}"}],
        },
    }
    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": widget_def, "source_integration": "foo"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()

    await widget_templates.load_widget_templates_from_db()

    entry = widget_templates.get_widget_template("t1")
    assert entry is not None
    assert entry["display"] == "inline"
    assert entry["package_id"]
    assert entry["package_version"] == 1
    widget_templates._widget_templates.clear()


@pytest.mark.asyncio
async def test_reload_tool_swaps_entry(sessionmaker_fixture):
    widget_templates._widget_templates.clear()
    wd = {"template": {"v": 1, "components": []}}
    with patch.object(
        widget_packages_seeder, "_collect_sources",
        return_value=_make_sources([
            {"tool_name": "t1", "widget_def": wd, "source_integration": "foo"},
        ]),
    ):
        await widget_packages_seeder.seed_widget_packages()
    await widget_templates.load_widget_templates_from_db()

    # Swap activation from seed → a fresh user row.
    async with sessionmaker_fixture() as db:
        seed = (await db.execute(select(WidgetTemplatePackage))).scalar_one()
        seed.is_active = False
        await db.flush()
        user = WidgetTemplatePackage(
            tool_name="t1",
            name="User",
            yaml_template=(
                "display: inline\n"
                "template:\n  v: 1\n  components:\n    - type: status\n      text: user-active\n"
            ),
            source="user",
            is_active=True,
        )
        db.add(user)
        await db.commit()

    await widget_templates.reload_tool("t1")
    entry = widget_templates.get_widget_template("t1")
    assert entry is not None
    body = entry["template"]
    assert body["components"][0]["text"] == "user-active"
    widget_templates._widget_templates.clear()
