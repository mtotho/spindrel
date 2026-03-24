"""Integration tests for elevation observability API endpoints."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_bot(db_session, bot_id: str = "test-bot") -> None:
    """Insert a bot row so FK-free queries can find it."""
    from app.db.models import Bot
    from sqlalchemy import select

    existing = (await db_session.execute(select(Bot).where(Bot.id == bot_id))).scalar()
    if existing:
        return
    db_session.add(Bot(
        id=bot_id,
        name="Test Bot",
        model="test/model",
        system_prompt="Test",
    ))
    await db_session.commit()


async def _seed_channel(db_session, channel_id: uuid.UUID, bot_id: str = "test-bot") -> uuid.UUID:
    from app.db.models import Channel
    db_session.add(Channel(
        id=channel_id,
        name="test-channel",
        bot_id=bot_id,
    ))
    await db_session.commit()
    return channel_id


async def _seed_elevation_log(db_session, *, bot_id: str, channel_id=None, was_elevated: bool = False):
    from app.db.models import ModelElevationLog
    entry = ModelElevationLog(
        id=uuid.uuid4(),
        bot_id=bot_id,
        channel_id=channel_id,
        base_model="test/model",
        model_chosen="test/elevated" if was_elevated else "test/model",
        was_elevated=was_elevated,
        classifier_score=0.55 if was_elevated else 0.25,
        elevation_reason="test" if was_elevated else None,
        rules_fired=["keyword_elevate"] if was_elevated else [],
        signal_scores={"keyword_elevate": 0.8} if was_elevated else {},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(entry)
    await db_session.commit()


# ---------------------------------------------------------------------------
# GET /api/v1/admin/bots/{bot_id}/elevation
# ---------------------------------------------------------------------------

class TestBotElevation:
    async def test_get_bot_elevation_not_found(self, client):
        resp = await client.get("/api/v1/admin/bots/nonexistent/elevation", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    async def test_get_bot_elevation_empty(self, client, db_session):
        await _seed_bot(db_session)
        resp = await client.get("/api/v1/admin/bots/test-bot/elevation", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "config" in data
        assert "recent" in data
        assert "stats" in data
        assert data["recent"] == []
        assert data["stats"]["total_decisions"] == 0

    async def test_get_bot_elevation_with_logs(self, client, db_session):
        await _seed_bot(db_session)
        await _seed_elevation_log(db_session, bot_id="test-bot", was_elevated=True)
        await _seed_elevation_log(db_session, bot_id="test-bot", was_elevated=False)

        resp = await client.get("/api/v1/admin/bots/test-bot/elevation", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recent"]) == 2
        assert data["stats"]["total_decisions"] == 2
        assert data["stats"]["elevated_count"] == 1

    async def test_get_bot_elevation_limit(self, client, db_session):
        await _seed_bot(db_session)
        await _seed_elevation_log(db_session, bot_id="test-bot", was_elevated=False)
        await _seed_elevation_log(db_session, bot_id="test-bot", was_elevated=True)

        resp = await client.get("/api/v1/admin/bots/test-bot/elevation?limit=1", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["recent"]) == 1


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/bots/{bot_id}/elevation
# ---------------------------------------------------------------------------

class TestBotElevationUpdate:
    async def test_update_bot_elevation_not_found(self, client):
        resp = await client.patch(
            "/api/v1/admin/bots/nonexistent/elevation",
            json={"elevation_enabled": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_update_bot_elevation_config(self, client, db_session):
        from unittest.mock import AsyncMock

        await _seed_bot(db_session)
        with patch("app.agent.bots.reload_bots", new_callable=AsyncMock):
            resp = await client.patch(
                "/api/v1/admin/bots/test-bot/elevation",
                json={"elevation_enabled": True, "elevation_threshold": 0.5},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["threshold"] == 0.5


# ---------------------------------------------------------------------------
# GET /api/v1/admin/channels/{channel_id}/elevation
# ---------------------------------------------------------------------------

class TestChannelElevation:
    async def test_get_channel_elevation_not_found(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/admin/channels/{fake_id}/elevation", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    async def test_get_channel_elevation_empty(self, client, db_session):
        ch_id = uuid.uuid4()
        await _seed_channel(db_session, ch_id)
        resp = await client.get(f"/api/v1/admin/channels/{ch_id}/elevation", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["recent"] == []
        assert data["stats"]["total_decisions"] == 0

    async def test_get_channel_elevation_with_logs(self, client, db_session):
        ch_id = uuid.uuid4()
        await _seed_channel(db_session, ch_id)
        await _seed_elevation_log(db_session, bot_id="test-bot", channel_id=ch_id, was_elevated=True)

        resp = await client.get(f"/api/v1/admin/channels/{ch_id}/elevation", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recent"]) == 1
        assert data["stats"]["elevated_count"] == 1


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/channels/{channel_id}/elevation
# ---------------------------------------------------------------------------

class TestChannelElevationUpdate:
    async def test_update_channel_elevation_not_found(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/admin/channels/{fake_id}/elevation",
            json={"elevation_enabled": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_update_channel_elevation_config(self, client, db_session):
        ch_id = uuid.uuid4()
        await _seed_channel(db_session, ch_id)
        resp = await client.patch(
            f"/api/v1/admin/channels/{ch_id}/elevation",
            json={"elevation_enabled": False, "elevation_threshold": 0.6},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["threshold"] == 0.6
