"""Round-trip test for the heartbeat ``include_pinned_widgets`` flag.

The flag opts a heartbeat into injecting the channel's pinned dashboard
widget context block into its system_preamble. We verify the admin API
PUT/GET pair persists it correctly and defaults to false.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import Channel, ChannelHeartbeat
from tests.integration.conftest import AUTH_HEADERS


async def _seed_channel(db, *, heartbeat_overrides: dict | None = None):
    channel_id = uuid.uuid4()
    heartbeat_overrides = dict(heartbeat_overrides or {})
    db.add(Channel(
        id=channel_id,
        name="hb-widget-flag",
        client_id=f"hb-widget-flag-{channel_id}",
        bot_id="test-bot",
    ))
    hb = ChannelHeartbeat(
        id=uuid.uuid4(),
        channel_id=channel_id,
        enabled=heartbeat_overrides.pop("enabled", False),
        interval_minutes=heartbeat_overrides.pop("interval_minutes", 60),
        prompt=heartbeat_overrides.pop("prompt", "check the pinned widgets"),
        **heartbeat_overrides,
    )
    db.add(hb)
    await db.commit()
    return channel_id


@pytest.mark.asyncio
async def test_heartbeat_get_returns_include_pinned_widgets_default_false(client, db_session):
    channel_id = await _seed_channel(db_session)

    resp = await client.get(
        f"/api/v1/admin/channels/{channel_id}/heartbeat",
        headers=AUTH_HEADERS,
    )

    assert resp.status_code == 200, resp.text
    config = resp.json()["config"]
    assert config is not None
    assert config["include_pinned_widgets"] is False


@pytest.mark.asyncio
async def test_heartbeat_put_persists_include_pinned_widgets(client, db_session):
    channel_id = await _seed_channel(db_session)

    update = {
        "interval_minutes": 60,
        "prompt": "check the pinned widgets",
        "include_pinned_widgets": True,
    }
    put_resp = await client.put(
        f"/api/v1/admin/channels/{channel_id}/heartbeat",
        headers=AUTH_HEADERS,
        json=update,
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json()["include_pinned_widgets"] is True

    get_resp = await client.get(
        f"/api/v1/admin/channels/{channel_id}/heartbeat",
        headers=AUTH_HEADERS,
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["config"]["include_pinned_widgets"] is True


@pytest.mark.asyncio
async def test_heartbeat_put_can_disable_include_pinned_widgets(client, db_session):
    channel_id = await _seed_channel(db_session, heartbeat_overrides={"include_pinned_widgets": True})

    update = {
        "interval_minutes": 60,
        "prompt": "check the pinned widgets",
        "include_pinned_widgets": False,
    }
    put_resp = await client.put(
        f"/api/v1/admin/channels/{channel_id}/heartbeat",
        headers=AUTH_HEADERS,
        json=update,
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json()["include_pinned_widgets"] is False


@pytest.mark.asyncio
async def test_heartbeat_put_disabled_clears_next_run_at(client, db_session):
    channel_id = await _seed_channel(
        db_session,
        heartbeat_overrides={
            "enabled": True,
            "next_run_at": datetime.now(timezone.utc) + timedelta(minutes=30),
        },
    )

    put_resp = await client.put(
        f"/api/v1/admin/channels/{channel_id}/heartbeat",
        headers=AUTH_HEADERS,
        json={
            "enabled": False,
            "interval_minutes": 60,
            "prompt": "disabled heartbeat",
        },
    )

    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    assert body["enabled"] is False
    assert body["next_run_at"] is None

    hb = (await db_session.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id == channel_id)
    )).scalar_one()
    assert hb.next_run_at is None


@pytest.mark.asyncio
async def test_heartbeat_put_enabled_schedules_when_missing(client, db_session):
    channel_id = await _seed_channel(
        db_session,
        heartbeat_overrides={
            "enabled": False,
            "next_run_at": None,
        },
    )

    put_resp = await client.put(
        f"/api/v1/admin/channels/{channel_id}/heartbeat",
        headers=AUTH_HEADERS,
        json={
            "enabled": True,
            "interval_minutes": 60,
            "prompt": "enabled heartbeat",
        },
    )

    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    assert body["enabled"] is True
    assert body["next_run_at"] is not None
