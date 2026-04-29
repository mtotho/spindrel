from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.mark.asyncio
async def test_admin_channel_widget_usefulness_empty_dashboard(client, db_session):
    channel = Channel(id=uuid.uuid4(), name="usefulness", bot_id="test-bot")
    db_session.add(channel)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/admin/channels/{channel.id}/widget-usefulness",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["channel_id"] == str(channel.id)
    assert data["dashboard_key"] == f"channel:{channel.id}"
    assert data["pin_count"] == 0
    assert data["recommendations"][0]["type"] == "missing_coverage"


@pytest.mark.asyncio
async def test_admin_channel_widget_usefulness_404(client):
    response = await client.get(
        f"/api/v1/admin/channels/{uuid.uuid4()}/widget-usefulness",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
