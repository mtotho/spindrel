"""Shared helpers for Mission Control router sub-modules."""
from __future__ import annotations

import asyncio
import logging
import os
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, Channel, ChannelMember, User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column verb mapping for humanizing timeline events
# ---------------------------------------------------------------------------

_COLUMN_VERBS: dict[str, str] = {
    "in progress": "was started",
    "done": "was completed",
    "review": "moved to review",
    "backlog": "moved back to backlog",
}


def humanize_event(raw: str) -> str:
    """Transform machine-readable timeline text into human-friendly prose."""
    m = re.match(
        r'Card \S+ moved to \*\*(.+?)\*\* \(was: .+?\) — "(.+?)"',
        raw,
    )
    if m:
        col, title = m.group(1), m.group(2)
        verb = _COLUMN_VERBS.get(col.lower(), f"moved to {col}")
        return f"**{title}** {verb}"

    m = re.match(r'New card created: \S+ "(.+?)" in \*\*(.+?)\*\*', raw)
    if m:
        title, col = m.group(1), m.group(2)
        return f"New task: **{title}** added to {col}"

    m = re.match(r"Plan approved: \*\*(.+?)\*\* \(\S+\)", raw)
    if m:
        return f"Plan **{m.group(1)}** was approved"

    m = re.match(r"Plan rejected: \*\*(.+?)\*\* \(\S+\)", raw)
    if m:
        return f"Plan **{m.group(1)}** was rejected"

    return raw


# ---------------------------------------------------------------------------
# Auth / user helpers
# ---------------------------------------------------------------------------

def get_user(auth) -> User | None:
    """Extract User from auth result. API keys get no user-scoping (admin-level)."""
    if isinstance(auth, User):
        return auth
    return None


def require_channel_access(channel: Channel, user: User | None):
    """Raise 403 if a user doesn't own the channel."""
    from fastapi import HTTPException
    if user and channel.user_id and channel.user_id != user.id:
        raise HTTPException(403, "Not your channel")


def get_bot(bot_id: str):
    """Get a bot config by ID."""
    from app.agent.bots import get_bot as _get_bot
    return _get_bot(bot_id)


# ---------------------------------------------------------------------------
# Channel tracking + prefs
# ---------------------------------------------------------------------------

async def tracked_channels(
    db: AsyncSession,
    user: User | None,
    prefs: dict | None = None,
    *,
    scope: str = "fleet",
) -> list[Channel]:
    """Get channels tracked by MC.

    Fleet: all workspace-enabled channels (everyone can see).
    Personal: workspace-enabled channels where user is a member.
    tracked_channel_ids pref still applies as additional filter.
    """
    q = select(Channel).where(Channel.channel_workspace_enabled == True)  # noqa: E712

    if user and scope == "personal":
        q = q.where(
            Channel.id.in_(
                select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)
            )
        )

    result = await db.execute(q.order_by(Channel.name))
    channels = list(result.scalars().all())

    if prefs and prefs.get("tracked_channel_ids"):
        tracked = set(prefs["tracked_channel_ids"])
        channels = [ch for ch in channels if str(ch.id) in tracked]

    return channels


async def get_mc_prefs(db: AsyncSession, user: User | None) -> dict:
    """Get MC preferences from user.integration_config."""
    if not user:
        return {}
    ic = user.integration_config or {}
    return ic.get("mission_control", {})


# ---------------------------------------------------------------------------
# DB existence checks (async — check MC SQLite for data)
# ---------------------------------------------------------------------------

async def has_kanban_data(channel: Channel) -> bool:
    """Check whether a channel has any kanban cards in the MC database."""
    try:
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanCard
        from sqlalchemy import func

        async with await mc_session() as session:
            count = (await session.execute(
                select(func.count(McKanbanCard.id))
                .where(McKanbanCard.channel_id == str(channel.id))
            )).scalar() or 0
            return count > 0
    except Exception:
        return False


async def has_timeline_data(channel: Channel) -> bool:
    """Check whether a channel has any timeline events in the MC database."""
    try:
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McTimelineEvent
        from sqlalchemy import func

        async with await mc_session() as session:
            count = (await session.execute(
                select(func.count(McTimelineEvent.id))
                .where(McTimelineEvent.channel_id == str(channel.id))
            )).scalar() or 0
            return count > 0
    except Exception:
        return False


async def has_plans_data(channel: Channel) -> bool:
    """Check whether a channel has any plans in the MC database."""
    try:
        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan
        from sqlalchemy import func

        async with await mc_session() as session:
            count = (await session.execute(
                select(func.count(McPlan.id))
                .where(McPlan.channel_id == str(channel.id))
            )).scalar() or 0
            return count > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# File reading helpers (async, for aggregation endpoints)
# ---------------------------------------------------------------------------

async def read_tasks_for_channel(channel: Channel) -> list[dict]:
    """Read kanban columns for a channel from MC SQLite DB."""
    try:
        from integrations.mission_control.services import _get_kanban_columns_as_dicts
        return await _get_kanban_columns_as_dicts(str(channel.id))
    except Exception:
        logger.debug("Could not read tasks for channel %s", channel.id, exc_info=True)
    return []


async def read_plans_for_channel(channel: Channel) -> list[dict]:
    """Read plans for a channel from MC SQLite DB."""
    try:
        from integrations.mission_control.services import _get_plans_as_dicts
        return await _get_plans_as_dicts(str(channel.id))
    except Exception:
        logger.debug("Could not read plans for channel %s", channel.id, exc_info=True)
    return []


async def read_timeline_for_channel(channel: Channel) -> list[dict]:
    """Read timeline events for a channel from MC SQLite DB."""
    try:
        from integrations.mission_control.services import get_timeline_events
        return await get_timeline_events(str(channel.id))
    except Exception:
        logger.debug("Could not read timeline for channel %s", channel.id, exc_info=True)
    return []


def plan_step_summary(plan: dict) -> str:
    """Build a concise summary of plan step states for task prompts."""
    steps = plan.get("steps", [])
    if not steps:
        return "No steps defined."
    lines = []
    next_step = None
    for s in steps:
        marker = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "skipped": "[-]", "failed": "[!]"}.get(s["status"], "[ ]")
        lines.append(f"  {s['position']}. {marker} {s['content']}")
        if next_step is None and s["status"] in ("pending", "in_progress"):
            next_step = s
    summary = "\n".join(lines)
    if next_step:
        summary += f"\n\nNext step: #{next_step['position']} — {next_step['content']}"
    return summary
