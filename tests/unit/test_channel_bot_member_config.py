"""Phase E.7 — JSONB PATCH seam: channel_bot_members.config

Pins the merge/delete contracts of ``update_bot_member_config`` against a real
SQLite DB. The silent-failure surface: if ``flag_modified`` is absent the ORM
skips the JSONB write, leaving stale config in the DB while the in-memory
object looks correct. Cross-session verification (expire_all + re-read) catches
this class of bug.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import Channel, ChannelBotMember
from app.routers.api_v1_channels import (
    UpdateBotMemberConfigRequest,
    update_bot_member_config,
)

pytestmark = pytest.mark.asyncio


async def _seed(
    db_session, *, config: dict | None = None, bot_id: str = "test-bot"
) -> tuple[uuid.UUID, str]:
    """Insert Channel + ChannelBotMember. Returns (channel_id, bot_id)."""
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name=f"ch-{channel_id.hex[:6]}", bot_id=bot_id))
    db_session.add(ChannelBotMember(channel_id=channel_id, bot_id=bot_id, config=config or {}))
    await db_session.commit()
    return channel_id, bot_id


class TestMergeContracts:
    async def test_when_config_empty_then_new_key_persisted(self, db_session):
        channel_id, bot_id = await _seed(db_session)
        out = await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(max_rounds=5),
            db=db_session,
            _auth=None,
        )
        assert out.config == {"max_rounds": 5}

    async def test_when_existing_keys_present_then_merge_preserves_both(self, db_session):
        channel_id, bot_id = await _seed(db_session, config={"auto_respond": True})
        out = await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(max_rounds=3),
            db=db_session,
            _auth=None,
        )
        assert out.config == {"auto_respond": True, "max_rounds": 3}

    async def test_when_null_sent_then_key_removed_not_nulled(self, db_session):
        channel_id, bot_id = await _seed(
            db_session, config={"max_rounds": 10, "auto_respond": True}
        )
        out = await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(max_rounds=None),
            db=db_session,
            _auth=None,
        )
        assert "max_rounds" not in out.config
        assert out.config.get("auto_respond") is True

    async def test_when_valid_response_styles_sent_then_all_accepted(self, db_session):
        for style in ("brief", "normal", "detailed"):
            channel_id, bot_id = await _seed(db_session, bot_id=f"bot-{style}")
            out = await update_bot_member_config(
                channel_id=channel_id,
                bot_id=bot_id,
                body=UpdateBotMemberConfigRequest(response_style=style),
                db=db_session,
                _auth=None,
            )
            assert out.config["response_style"] == style

    async def test_when_invalid_response_style_then_422(self, db_session):
        channel_id, bot_id = await _seed(db_session)
        with pytest.raises(HTTPException) as exc:
            await update_bot_member_config(
                channel_id=channel_id,
                bot_id=bot_id,
                body=UpdateBotMemberConfigRequest(response_style="wrong"),
                db=db_session,
                _auth=None,
            )
        assert exc.value.status_code == 422
        assert "response_style" in exc.value.detail

    async def test_when_bot_member_missing_then_404(self, db_session):
        channel_id = uuid.uuid4()
        db_session.add(Channel(id=channel_id, name="ch", bot_id="owner"))
        await db_session.commit()
        with pytest.raises(HTTPException) as exc:
            await update_bot_member_config(
                channel_id=channel_id,
                bot_id="ghost-bot",
                body=UpdateBotMemberConfigRequest(max_rounds=1),
                db=db_session,
                _auth=None,
            )
        assert exc.value.status_code == 404


class TestPersistenceContracts:
    async def test_mutation_survives_expire_all_round_trip(self, db_session):
        """Verify flag_modified fires: expire_all forces a DB round-trip and
        confirms the JSONB value was actually written, not just mutated in memory."""
        channel_id, bot_id = await _seed(db_session, config={"auto_respond": False})
        await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(max_rounds=7),
            db=db_session,
            _auth=None,
        )
        db_session.expire_all()
        row = (await db_session.execute(
            select(ChannelBotMember).where(
                ChannelBotMember.channel_id == channel_id,
                ChannelBotMember.bot_id == bot_id,
            )
        )).scalar_one()
        assert row.config == {"auto_respond": False, "max_rounds": 7}

    async def test_second_patch_accumulates_on_first(self, db_session):
        """Two sequential PATCHes compose: the second reads the committed result
        of the first, not the original empty config."""
        channel_id, bot_id = await _seed(db_session)
        await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(max_rounds=3),
            db=db_session,
            _auth=None,
        )
        db_session.expire_all()
        out = await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(auto_respond=True),
            db=db_session,
            _auth=None,
        )
        assert out.config == {"max_rounds": 3, "auto_respond": True}

    async def test_removal_then_re_add_produces_correct_config(self, db_session):
        """Remove a key and re-add it in successive PATCHes: final config has
        the new value, not the old one and not a tombstone None."""
        channel_id, bot_id = await _seed(db_session, config={"max_rounds": 99})
        await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(max_rounds=None),
            db=db_session,
            _auth=None,
        )
        db_session.expire_all()
        out = await update_bot_member_config(
            channel_id=channel_id,
            bot_id=bot_id,
            body=UpdateBotMemberConfigRequest(max_rounds=5),
            db=db_session,
            _auth=None,
        )
        assert out.config == {"max_rounds": 5}
        assert None not in out.config.values()
