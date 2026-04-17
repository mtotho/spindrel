"""Factories for Channel and ChannelBotMember."""
from __future__ import annotations

import uuid

from app.db.models import Channel, ChannelBotMember


def build_channel(**overrides) -> Channel:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        name=f"test-channel-{suffix}",
        bot_id=f"bot-{suffix}",
    )
    return Channel(**{**defaults, **overrides})


def build_channel_bot_member(**overrides) -> ChannelBotMember:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id=f"member-bot-{suffix}",
        config={},
    )
    return ChannelBotMember(**{**defaults, **overrides})
