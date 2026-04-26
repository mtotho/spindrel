"""Round-trip test for the heartbeat ``include_pinned_widgets`` flag.

The flag opts a heartbeat into injecting the channel's pinned dashboard
widget context block into its system_preamble. We verify the admin API
PUT/GET pair persists it correctly and defaults to false.
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel, ChannelHeartbeat
from tests.integration.conftest import AUTH_HEADERS


async def _seed_channel(db, *, heartbeat_overrides: dict | None = None):
    channel_id = uuid.uuid4()
    db.add(Channel(
        id=channel_id,
        name="hb-widget-flag",
        client_id=f"hb-widget-flag-{channel_id}",
        bot_id="test-bot",
    ))
    hb = ChannelHeartbeat(
        id=uuid.uuid4(),
        channel_id=channel_id,
        enabled=False,
        interval_minutes=60,
        prompt="check the pinned widgets",
        **(heartbeat_overrides or {}),
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
