"""Integration tests for bot member config PATCH endpoint.

Covers:
- PATCH config sets fields correctly
- Partial updates preserve existing fields
- Setting null clears a field
- Invalid response_style is rejected
- Config appears in GET list response
"""
import uuid

import pytest

from app.db.models import Channel, ChannelBotMember

AUTH_HEADERS = {"Authorization": "Bearer test-key"}

pytestmark = pytest.mark.asyncio


async def _create_channel(db_session, bot_id="test-bot"):
    ch = Channel(id=uuid.uuid4(), name="test-ch", bot_id=bot_id)
    db_session.add(ch)
    await db_session.commit()
    return ch.id


async def _add_member(db_session, channel_id, bot_id="helper-bot", config=None):
    bm = ChannelBotMember(
        id=uuid.uuid4(),
        channel_id=channel_id,
        bot_id=bot_id,
        config=config or {},
    )
    db_session.add(bm)
    await db_session.commit()
    return bm


class TestPatchBotMemberConfig:
    async def test_set_config_fields(self, client, db_session):
        ch_id = await _create_channel(db_session)
        await _add_member(db_session, ch_id, "helper-bot")

        resp = await client.patch(
            f"/api/v1/channels/{ch_id}/bot-members/helper-bot/config",
            json={"auto_respond": True, "response_style": "brief", "priority": 2},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["auto_respond"] is True
        assert body["config"]["response_style"] == "brief"
        assert body["config"]["priority"] == 2

    async def test_partial_update_preserves_existing(self, client, db_session):
        ch_id = await _create_channel(db_session)
        await _add_member(db_session, ch_id, "helper-bot", config={"auto_respond": True, "priority": 5})

        # Update only response_style — auto_respond and priority should remain
        resp = await client.patch(
            f"/api/v1/channels/{ch_id}/bot-members/helper-bot/config",
            json={"response_style": "detailed"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert cfg["auto_respond"] is True
        assert cfg["priority"] == 5
        assert cfg["response_style"] == "detailed"

    async def test_null_clears_field(self, client, db_session):
        ch_id = await _create_channel(db_session)
        await _add_member(db_session, ch_id, "helper-bot", config={"model_override": "gpt-4o", "auto_respond": True})

        resp = await client.patch(
            f"/api/v1/channels/{ch_id}/bot-members/helper-bot/config",
            json={"model_override": None},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert "model_override" not in cfg
        assert cfg["auto_respond"] is True  # untouched

    async def test_invalid_response_style_rejected(self, client, db_session):
        ch_id = await _create_channel(db_session)
        await _add_member(db_session, ch_id, "helper-bot")

        resp = await client.patch(
            f"/api/v1/channels/{ch_id}/bot-members/helper-bot/config",
            json={"response_style": "invalid_style"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    async def test_not_found_returns_404(self, client, db_session):
        ch_id = await _create_channel(db_session)

        resp = await client.patch(
            f"/api/v1/channels/{ch_id}/bot-members/nonexistent/config",
            json={"auto_respond": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_config_in_list_response(self, client, db_session):
        ch_id = await _create_channel(db_session)
        await _add_member(db_session, ch_id, "helper-bot", config={"auto_respond": True, "response_style": "brief"})

        resp = await client.get(
            f"/api/v1/channels/{ch_id}/bot-members",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        members = resp.json()
        assert len(members) == 1
        assert members[0]["config"]["auto_respond"] is True
        assert members[0]["config"]["response_style"] == "brief"

    async def test_set_all_config_fields(self, client, db_session):
        ch_id = await _create_channel(db_session)
        await _add_member(db_session, ch_id, "helper-bot")

        resp = await client.patch(
            f"/api/v1/channels/{ch_id}/bot-members/helper-bot/config",
            json={
                "max_rounds": 5,
                "auto_respond": True,
                "response_style": "detailed",
                "system_prompt_addon": "Be concise.",
                "model_override": "gpt-4o",
                "priority": 1,
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert cfg["max_rounds"] == 5
        assert cfg["auto_respond"] is True
        assert cfg["response_style"] == "detailed"
        assert cfg["system_prompt_addon"] == "Be concise."
        assert cfg["model_override"] == "gpt-4o"
        assert cfg["priority"] == 1

    async def test_empty_body_is_noop(self, client, db_session):
        ch_id = await _create_channel(db_session)
        await _add_member(db_session, ch_id, "helper-bot", config={"auto_respond": True})

        resp = await client.patch(
            f"/api/v1/channels/{ch_id}/bot-members/helper-bot/config",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["config"]["auto_respond"] is True
