"""Auto-create the default workspace and auto-enroll all bots.

Called during startup after bots are loaded. Ensures exactly one workspace
exists and every bot is enrolled as a member. Both functions are idempotent.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, SharedWorkspace, SharedWorkspaceBot

logger = logging.getLogger(__name__)


async def ensure_default_workspace(db: AsyncSession) -> SharedWorkspace:
    """Return the single default workspace, creating it if none exists.

    If multiple workspaces already exist (legacy), returns the oldest one.
    """
    result = await db.execute(
        select(SharedWorkspace).order_by(SharedWorkspace.created_at.asc()).limit(1)
    )
    ws = result.scalar_one_or_none()
    if ws is not None:
        return ws

    ws = SharedWorkspace(name="Default Workspace")
    db.add(ws)
    await db.flush()
    logger.info("Created default workspace: %s (id=%s)", ws.name, ws.id)
    await db.commit()
    return ws


async def ensure_all_bots_enrolled(db: AsyncSession, workspace_id) -> int:
    """Enroll every bot into the workspace. Returns count of newly added rows.

    Uses INSERT ... ON CONFLICT DO NOTHING so existing memberships (and their
    roles / cwd_override / write_access) are preserved.
    """
    bot_ids = (await db.execute(select(BotRow.id))).scalars().all()
    if not bot_ids:
        return 0

    stmt = pg_insert(SharedWorkspaceBot).values(
        [{"workspace_id": workspace_id, "bot_id": bid, "role": "member"} for bid in bot_ids]
    ).on_conflict_do_nothing(index_elements=["bot_id"])

    result = await db.execute(stmt)
    await db.commit()
    added = result.rowcount  # type: ignore[union-attr]
    return added
