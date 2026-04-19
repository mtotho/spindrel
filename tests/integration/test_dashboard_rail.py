"""Integration tests for per-user + everyone rail pinning.

The ``client`` fixture authenticates as a static admin API key — covers
the admin write paths. Non-admin enforcement (403 on scope=everyone) is
unit-tested at the service layer in ``tests/unit/test_dashboard_rail.py``.
"""
from __future__ import annotations

import uuid

import pytest


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.mark.asyncio
async def test_list_hydrates_rail_block(client):
    """Every dashboard in the list carries a ``rail`` block."""
    r = await client.get("/api/v1/widgets/dashboards", headers=AUTH_HEADERS)
    assert r.status_code == 200
    rows = r.json()["dashboards"]
    assert rows
    for row in rows:
        assert "rail" in row
        assert row["rail"].keys() >= {"me_pinned", "everyone_pinned", "effective_position"}


@pytest.mark.asyncio
async def test_put_rail_everyone_reflects_in_list(client):
    await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home"},
        headers=AUTH_HEADERS,
    )

    r = await client.put(
        "/api/v1/widgets/dashboards/home/rail",
        json={"scope": "everyone", "rail_position": 2},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["rail"]["everyone_pinned"] is True
    assert r.json()["rail"]["effective_position"] == 2

    listing = await client.get(
        "/api/v1/widgets/dashboards", headers=AUTH_HEADERS,
    )
    by_slug = {d["slug"]: d for d in listing.json()["dashboards"]}
    assert by_slug["home"]["rail"]["everyone_pinned"] is True
    assert by_slug["home"]["rail"]["effective_position"] == 2


@pytest.mark.asyncio
async def test_delete_rail_clears_pin(client):
    await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home"},
        headers=AUTH_HEADERS,
    )
    await client.put(
        "/api/v1/widgets/dashboards/home/rail",
        json={"scope": "everyone"},
        headers=AUTH_HEADERS,
    )

    r = await client.delete(
        "/api/v1/widgets/dashboards/home/rail?scope=everyone",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["rail"]["everyone_pinned"] is False


@pytest.mark.asyncio
async def test_put_rail_404_unknown_slug(client):
    r = await client.put(
        "/api/v1/widgets/dashboards/never-existed/rail",
        json={"scope": "everyone"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_channel_dashboard_rail_pin_lazy_creates(client, db_session):
    """PUT /rail on a channel:<uuid> slug creates the dashboard row on the fly."""
    from app.db.models import Channel, WidgetDashboard
    from sqlalchemy import select

    ch = Channel(id=uuid.uuid4(), name="general", bot_id="default")
    db_session.add(ch)
    await db_session.commit()

    slug = f"channel:{ch.id}"
    r = await client.put(
        f"/api/v1/widgets/dashboards/{slug}/rail",
        json={"scope": "everyone"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["rail"]["everyone_pinned"] is True

    row = (await db_session.execute(
        select(WidgetDashboard).where(WidgetDashboard.slug == slug),
    )).scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
async def test_create_no_longer_accepts_legacy_fields(client):
    """Body used to accept ``pin_to_rail`` — it's gone; extra fields ignored.

    Pydantic silently drops unknown keys, so the create should still succeed
    without an unintended side-effect. The rail stays off until a follow-up
    PUT /rail call.
    """
    r = await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home", "pin_to_rail": True},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["rail"] == {
        "me_pinned": False,
        "everyone_pinned": False,
        "effective_position": None,
    }


@pytest.mark.asyncio
async def test_put_rail_rejects_bad_scope(client):
    await client.post(
        "/api/v1/widgets/dashboards",
        json={"slug": "home", "name": "Home"},
        headers=AUTH_HEADERS,
    )
    r = await client.put(
        "/api/v1/widgets/dashboards/home/rail",
        json={"scope": "squad"},
        headers=AUTH_HEADERS,
    )
    # Literal type validation → 422 from FastAPI.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_everyone_pin_visible_across_dashboards(client):
    """Each dashboard owns its own rail row — pinning 'home' doesn't pin 'work'."""
    for slug in ("home", "work"):
        await client.post(
            "/api/v1/widgets/dashboards",
            json={"slug": slug, "name": slug.title()},
            headers=AUTH_HEADERS,
        )

    await client.put(
        "/api/v1/widgets/dashboards/home/rail",
        json={"scope": "everyone", "rail_position": 1},
        headers=AUTH_HEADERS,
    )

    listing = await client.get(
        "/api/v1/widgets/dashboards", headers=AUTH_HEADERS,
    )
    by_slug = {d["slug"]: d for d in listing.json()["dashboards"]}
    assert by_slug["home"]["rail"]["everyone_pinned"] is True
    assert by_slug["work"]["rail"]["everyone_pinned"] is False
