"""DiscordTarget — typed dispatch destination for the Discord integration.

Self-registers with ``app.domain.target_registry`` at module import.
The integration discovery loop auto-imports this module before
``renderer.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from integrations.sdk import target_registry, BaseTarget as _BaseTarget


@dataclass(frozen=True)
class DiscordTarget(_BaseTarget):
    type: ClassVar[Literal["discord"]] = "discord"
    integration_id: ClassVar[str] = "discord"

    channel_id: str
    token: str
    # ``user_message_id`` is the snowflake of the inbound user message
    # that triggered the turn. The Discord renderer / reaction hooks
    # use it to add hourglass + tool-name emoji reactions to the
    # original user message. Written into ``dispatch_config`` by
    # ``integrations/discord/message_handlers.py:dispatch`` and read
    # by ``integrations/discord/hooks.py:_get_discord_ref``. Optional
    # because admin-injected messages and slash commands sometimes
    # have no inbound user message to react to.
    user_message_id: str | None = None


target_registry.register(DiscordTarget)
