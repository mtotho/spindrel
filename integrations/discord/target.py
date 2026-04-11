"""DiscordTarget — typed dispatch destination for the Discord integration.

Self-registers with ``app.domain.target_registry`` at module import.
The integration discovery loop auto-imports this module before
``renderer.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from app.domain import target_registry
from app.domain.dispatch_target import _BaseTarget


@dataclass(frozen=True)
class DiscordTarget(_BaseTarget):
    type: ClassVar[Literal["discord"]] = "discord"
    integration_id: ClassVar[str] = "discord"

    channel_id: str
    token: str


target_registry.register(DiscordTarget)
