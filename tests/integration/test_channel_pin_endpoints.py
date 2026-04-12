"""Integration tests for channel pin/unpin endpoints.

POST /api/v1/channels/{channel_id}/pins
DELETE /api/v1/channels/{channel_id}/pins?path=...
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Channel
from tests.integration.conftest import client, db_session, engine, _TEST_REGISTRY  # noqa: F401

# Mock invalidate_channel since it opens its own DB session
@pytest.fixture(autouse=True)
def _mock_cache():
    with patch(
        "app.services.pinned_panels.invalidate_channel",
        new_callable=AsyncMock,
    ):
        yield


@pytest.mark.asyncio
async def test_pin_file_creates_entry(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "report.md", "position": "right"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["path"] == "report.md"
    assert body["position"] == "right"
    assert body["pinned_by"] == "user"
    assert "pinned_at" in body


@pytest.mark.asyncio
async def test_pin_deduplicates_by_path(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    # Pin twice
    await client.post(f"/api/v1/channels/{ch.id}/pins", json={"path": "report.md", "position": "right"})
    await client.post(f"/api/v1/channels/{ch.id}/pins", json={"path": "report.md", "position": "bottom"})

    # Fetch channel and check only one entry
    await db_session.refresh(ch)
    panels = (ch.config or {}).get("pinned_panels", [])
    assert len(panels) == 1
    assert panels[0]["position"] == "bottom"


@pytest.mark.asyncio
async def test_unpin_removes_entry(client, db_session):
    ch = Channel(
        id=uuid.uuid4(),
        name="test-ch",
        bot_id="test-bot",
        config={"pinned_panels": [
            {"path": "report.md", "position": "right", "pinned_at": "2026-01-01T00:00:00Z", "pinned_by": "user"},
        ]},
    )
    db_session.add(ch)
    await db_session.commit()

    res = await client.delete(f"/api/v1/channels/{ch.id}/pins?path=report.md")
    assert res.status_code == 200

    await db_session.refresh(ch)
    panels = (ch.config or {}).get("pinned_panels", [])
    assert len(panels) == 0


@pytest.mark.asyncio
async def test_unpin_nonexistent_returns_404(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    res = await client.delete(f"/api/v1/channels/{ch.id}/pins?path=nonexistent.md")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_pin_invalid_position_returns_422(client, db_session):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id="test-bot", config={})
    db_session.add(ch)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/channels/{ch.id}/pins",
        json={"path": "report.md", "position": "left"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_pin_channel_not_found(client, db_session):
    fake_id = uuid.uuid4()
    res = await client.post(
        f"/api/v1/channels/{fake_id}/pins",
        json={"path": "report.md"},
    )
    assert res.status_code == 404
