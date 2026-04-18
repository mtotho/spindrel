"""Factory for BotHook."""
from __future__ import annotations

import uuid

from app.db.models import BotHook


def build_bot_hook(bot_id: str, **overrides) -> BotHook:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        bot_id=bot_id,
        name=f"hook-{suffix}",
        trigger="before_access",
        conditions={"path": "/workspace/*"},
        command="echo hi",
        cooldown_seconds=60,
        on_failure="block",
        enabled=True,
    )
    return BotHook(**{**defaults, **overrides})
