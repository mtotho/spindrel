"""WorkSurface participant authorization and boundary audit events."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_client_id,
    current_correlation_id,
    current_session_id,
)
from app.db.models import Channel, ChannelBotMember

WorkSurfaceAccessMode = Literal["read", "write", "search", "history"]


@dataclass(frozen=True)
class ChannelWorkSurfaceAccess:
    allowed: bool
    reason: Literal["primary", "member", "missing_bot", "missing_channel", "not_participant"]
    channel_id: uuid.UUID
    actor_bot_id: str | None
    owner_bot_id: str | None = None

    @property
    def error(self) -> str | None:
        if self.allowed:
            return None
        if self.reason == "missing_channel":
            return "Access denied: channel not found."
        if self.reason == "missing_bot":
            return "Access denied: no bot context available."
        return "Access denied: this bot is not a participant in the requested channel."


async def authorize_channel_worksurface(
    db: AsyncSession,
    *,
    actor_bot_id: str | None,
    channel_id: uuid.UUID,
) -> ChannelWorkSurfaceAccess:
    """Allow only channel primary and member bots to touch a channel WorkSurface."""
    if not actor_bot_id:
        return ChannelWorkSurfaceAccess(
            allowed=False,
            reason="missing_bot",
            channel_id=channel_id,
            actor_bot_id=None,
        )

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return ChannelWorkSurfaceAccess(
            allowed=False,
            reason="missing_channel",
            channel_id=channel_id,
            actor_bot_id=actor_bot_id,
        )

    owner_bot_id = str(channel.bot_id)
    if owner_bot_id == actor_bot_id:
        return ChannelWorkSurfaceAccess(
            allowed=True,
            reason="primary",
            channel_id=channel_id,
            actor_bot_id=actor_bot_id,
            owner_bot_id=owner_bot_id,
        )

    is_member = await db.scalar(
        select(exists().where(
            ChannelBotMember.channel_id == channel_id,
            ChannelBotMember.bot_id == actor_bot_id,
        ))
    )
    if is_member:
        return ChannelWorkSurfaceAccess(
            allowed=True,
            reason="member",
            channel_id=channel_id,
            actor_bot_id=actor_bot_id,
            owner_bot_id=owner_bot_id,
        )

    return ChannelWorkSurfaceAccess(
        allowed=False,
        reason="not_participant",
        channel_id=channel_id,
        actor_bot_id=actor_bot_id,
        owner_bot_id=owner_bot_id,
    )


async def record_worksurface_boundary_event(
    decision: ChannelWorkSurfaceAccess,
    *,
    mode: WorkSurfaceAccessMode,
    source_tool: str,
    path: str | None = None,
) -> None:
    """Persist a trace event for cross-channel WorkSurface access decisions."""
    from app.agent.recording import _record_trace_event

    event_type = (
        "worksurface_boundary_access"
        if decision.allowed
        else "worksurface_boundary_denied"
    )
    await _record_trace_event(
        correlation_id=current_correlation_id.get(),
        session_id=current_session_id.get(),
        bot_id=decision.actor_bot_id or current_bot_id.get(),
        client_id=current_client_id.get(),
        event_type=event_type,
        event_name=source_tool,
        data={
            "actor_bot_id": decision.actor_bot_id,
            "target_channel_id": str(decision.channel_id),
            "owner_bot_id": decision.owner_bot_id,
            "mode": mode,
            "source_tool": source_tool,
            "reason": decision.reason,
            "allowed": decision.allowed,
            "current_channel_id": (
                str(current_channel_id.get()) if current_channel_id.get() else None
            ),
            "path": path,
        },
    )
