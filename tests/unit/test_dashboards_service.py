"""Unit tests for app/services/dashboards.py."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.dashboard_pins import create_pin, list_pins
from app.services.dashboards import (
    create_dashboard,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
    redirect_target_slug,
    touch_last_viewed,
    update_dashboard,
)


def _env(label: str = "x") -> dict:
    return {
        "content_type": "application/vnd.spindrel.components+json",
        "body": "{}",
        "plain_body": "ok",
        "display": "inline",
        "truncated": False,
        "record_id": None,
        "byte_size": 2,
        "display_label": label,
    }


@pytest.mark.asyncio
async def test_default_is_preseeded(db_session):
    row = await get_dashboard(db_session, "default")
    assert row.slug == "default"
    assert row.name == "Default"


@pytest.mark.asyncio
async def test_create_and_list(db_session):
    await create_dashboard(db_session, slug="home", name="Home", icon="Home", pin_to_rail=True)
    rows = await list_dashboards(db_session)
    slugs = [r.slug for r in rows]
    assert "home" in slugs and "default" in slugs


@pytest.mark.asyncio
async def test_create_rejects_reserved_slug(db_session):
    for reserved in ("default", "dev", "new"):
        with pytest.raises(HTTPException) as exc:
            await create_dashboard(db_session, slug=reserved, name="X")
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_rejects_bad_slug_format(db_session):
    for bad in ("Caps", "with space", "-leading", "", "a" * 49):
        with pytest.raises(HTTPException) as exc:
            await create_dashboard(db_session, slug=bad, name="X")
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_rejects_duplicate_slug(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    with pytest.raises(HTTPException) as exc:
        await create_dashboard(db_session, slug="home", name="Home Again")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_changes_metadata(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    updated = await update_dashboard(
        db_session, "home",
        {"name": "Home Office", "icon": "Briefcase", "pin_to_rail": True},
    )
    assert updated.name == "Home Office"
    assert updated.icon == "Briefcase"
    assert updated.pin_to_rail is True


@pytest.mark.asyncio
async def test_delete_removes_dashboard(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    await delete_dashboard(db_session, "home")
    with pytest.raises(HTTPException) as exc:
        await get_dashboard(db_session, "home")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_default_is_forbidden(db_session):
    with pytest.raises(HTTPException) as exc:
        await delete_dashboard(db_session, "default")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_cascades_pins(db_session):
    """Deleting a dashboard drops its pins (explicit parity with FK cascade)."""
    await create_dashboard(db_session, slug="home", name="Home")
    await create_pin(
        db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
        dashboard_key="home",
    )
    await delete_dashboard(db_session, "home")
    with pytest.raises(HTTPException):
        await get_dashboard(db_session, "home")
    pins = await list_pins(db_session, dashboard_key="home")
    assert pins == []


@pytest.mark.asyncio
async def test_touch_last_viewed_drives_redirect_target(db_session):
    await create_dashboard(db_session, slug="home", name="Home")
    assert await redirect_target_slug(db_session) == "default"
    await touch_last_viewed(db_session, "home")
    assert await redirect_target_slug(db_session) == "home"


@pytest.mark.asyncio
async def test_create_pin_rejects_unknown_dashboard(db_session):
    with pytest.raises(HTTPException) as exc:
        await create_pin(
            db_session, source_kind="adhoc", tool_name="t", envelope=_env(),
            dashboard_key="nope",
        )
    assert exc.value.status_code == 404
