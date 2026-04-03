"""Test that get_or_create_channel does NOT overwrite bot_id on existing channels.

Regression test for: integration webhooks (Slack, BB) calling get_or_create_channel
with their own default bot_id, clobbering the user's configured bot_id.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models import Channel, ChannelIntegration
from app.services.channels import get_or_create_channel

pytestmark = pytest.mark.asyncio


async def _make_channel(db, *, bot_id="custom-bot", client_id=None):
    """Insert a channel directly (simulating UI creation)."""
    ch = Channel(
        id=uuid.uuid4(),
        name="test-channel",
        bot_id=bot_id,
        client_id=client_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(ch)
    await db.flush()
    return ch


async def _bind_integration(db, channel, *, integration_type="slack", client_id="slack:C123"):
    """Create a ChannelIntegration binding (simulating UI binding)."""
    binding = ChannelIntegration(
        channel_id=channel.id,
        integration_type=integration_type,
        client_id=client_id,
    )
    db.add(binding)
    await db.flush()
    return binding


class TestGetOrCreateDoesNotOverwriteBotId:
    """get_or_create_channel must NOT clobber bot_id on existing channels."""

    async def test_existing_channel_by_client_id_preserves_bot(self, db_session):
        """Channel found via Channel.client_id -- bot_id must not change."""
        ch = await _make_channel(db_session, bot_id="custom-bot", client_id="slack:C999")

        result = await get_or_create_channel(
            db_session,
            client_id="slack:C999",
            bot_id="different-bot",
        )

        assert result.id == ch.id
        assert result.bot_id == "custom-bot", (
            "bot_id was overwritten by get_or_create_channel"
        )

    async def test_existing_channel_via_binding_preserves_bot(self, db_session):
        """Channel found via ChannelIntegration binding -- bot_id must not change."""
        ch = await _make_channel(db_session, bot_id="my-bot")
        await _bind_integration(db_session, ch, integration_type="slack", client_id="slack:C456")

        result = await get_or_create_channel(
            db_session,
            client_id="slack:C456",
            bot_id="slack-default-bot",
        )

        assert result.id == ch.id
        assert result.bot_id == "my-bot", (
            "bot_id was overwritten via binding lookup"
        )

    async def test_existing_channel_by_id_preserves_bot(self, db_session):
        """Channel found by explicit channel_id -- bot_id must not change."""
        ch = await _make_channel(db_session, bot_id="original-bot")

        result = await get_or_create_channel(
            db_session,
            channel_id=ch.id,
            bot_id="webhook-bot",
        )

        assert result.id == ch.id
        assert result.bot_id == "original-bot", (
            "bot_id was overwritten by channel_id lookup"
        )

    async def test_dispatch_config_not_overwritten(self, db_session):
        """dispatch_config should not be overwritten on existing channels."""
        ch = await _make_channel(db_session, client_id="bb:test-chat")
        ch.dispatch_config = {"type": "bluebubbles", "chat_guid": "test-chat"}
        await db_session.flush()

        result = await get_or_create_channel(
            db_session,
            client_id="bb:test-chat",
            bot_id="default",
            dispatch_config={"type": "bluebubbles", "chat_guid": "test-chat", "extra": "field"},
        )

        assert result.id == ch.id
        assert result.dispatch_config == {"type": "bluebubbles", "chat_guid": "test-chat"}, (
            "dispatch_config was overwritten on existing channel"
        )

    async def test_new_channel_uses_provided_bot_id(self, db_session):
        """Brand new channel should use the bot_id from the caller."""
        with patch("app.services.channels._auto_set_workspace_id"):
            result = await get_or_create_channel(
                db_session,
                client_id="slack:CNEW123",
                bot_id="new-bot",
            )

        assert result.bot_id == "new-bot"
