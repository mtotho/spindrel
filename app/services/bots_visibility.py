"""Bot visibility + per-user access checks for User Management Phase 5.

Admin → bypass. Owner (``bot.user_id == user.id``) → bypass. Otherwise a
row in ``bot_grants(bot_id, user_id)`` is required.

Mirrors the shape of ``app/services/channels.py::apply_channel_visibility``
so the access model is consistent across channels and bots.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, BotGrant, User


def apply_bot_visibility(stmt, user: Any):
    """Filter a ``select(Bot)`` statement so only bots the user may use remain.

    - API-key auth (``user`` is not a ``User`` — e.g. a static admin key) or
      ``user.is_admin`` → no filter applied.
    - Other authenticated users → owner OR grantee rows only.
    """
    if user is None or not isinstance(user, User):
        return stmt
    if user.is_admin:
        return stmt
    return stmt.where(
        or_(
            Bot.user_id == user.id,
            Bot.id.in_(
                select(BotGrant.bot_id).where(BotGrant.user_id == user.id)
            ),
        )
    )


async def can_user_use_bot(db: AsyncSession, user: Any, bot: Bot) -> bool:
    """Return True if ``user`` is admin, owner, or has a grant on ``bot``."""
    if user is None:
        return False
    if not isinstance(user, User):
        # API-key auth principals use their own scope checks; this helper
        # is only meaningful for concrete User rows.
        return False
    if user.is_admin:
        return True
    if bot.user_id is not None and bot.user_id == user.id:
        return True
    grant_id = await db.scalar(
        select(BotGrant.bot_id)
        .where(BotGrant.bot_id == bot.id, BotGrant.user_id == user.id)
        .limit(1)
    )
    return grant_id is not None
