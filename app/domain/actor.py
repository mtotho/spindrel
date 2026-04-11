"""ActorRef — first-class sender identity attached to every Message.

Replaces the loose `sender_id` / `sender_display_name` strings sprinkled
across `msg_metadata`. A renderer that needs to attribute a message to
"@mtoth" or "Spike Alert" or a delegated bot reads `message.actor`,
not a free-form metadata dict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ActorKind = Literal["user", "bot", "system", "tool", "delegation"]


@dataclass(frozen=True)
class ActorRef:
    """Identifies who or what produced a message.

    Fields:
        kind: high-level role — user, bot, system, tool, delegation
        id: stable platform-or-spindrel id (slack user id, bot id, "spike_alert", etc.)
        display_name: human-readable name; renderers use this for attribution
        avatar: optional avatar URL or emoji shortcode
    """

    kind: ActorKind
    id: str
    display_name: str | None = None
    avatar: str | None = None

    @classmethod
    def system(cls, id: str, display_name: str | None = None) -> "ActorRef":
        return cls(kind="system", id=id, display_name=display_name or id)

    @classmethod
    def bot(cls, bot_id: str, display_name: str | None = None) -> "ActorRef":
        return cls(kind="bot", id=bot_id, display_name=display_name)

    @classmethod
    def user(cls, user_id: str, display_name: str | None = None) -> "ActorRef":
        return cls(kind="user", id=user_id, display_name=display_name)
