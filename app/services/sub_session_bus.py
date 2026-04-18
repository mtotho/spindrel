"""Sub-session → parent-channel bus bridge.

A sub-session (``Session.channel_id is None``, ``parent_session_id`` set) is
reachable only through its parent channel. The in-process channel event bus
is keyed by ``channel_id``, so when a sub-session emits Messages or turn
events, they need to be republished on the parent channel's bus so
subscribers (the run-view modal in the UI) can receive them.

The UI discriminates parent-channel vs. sub-session events by the
``session_id`` that every event payload already carries: the modal keeps
events where ``payload.session_id == run_session_id``; the parent channel
view drops them.

This module centralizes the parent-channel resolution so callers don't have
to walk ``parent_session_id`` chains inline.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session

logger = logging.getLogger(__name__)

MAX_WALK_DEPTH = 16


async def resolve_bus_channel_id(
    db: AsyncSession,
    session_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Return the channel_id to publish bus events on for ``session_id``.

    - Channel session (``channel_id`` set) → that channel.
    - Sub-session (``channel_id`` None, ``parent_session_id`` set) → walks
      up the chain and returns the first ancestor's ``channel_id``.
    - Orphan session (no channel ancestor) → None.

    Guarded with a bounded walk so a cyclic/corrupt graph can't spin.
    """
    if session_id is None:
        return None
    current = await db.get(Session, session_id)
    seen: set[uuid.UUID] = set()
    depth = 0
    while current is not None and depth < MAX_WALK_DEPTH:
        if current.id in seen:
            logger.warning(
                "resolve_bus_channel_id: cycle detected at session %s", current.id,
            )
            return None
        seen.add(current.id)
        if current.channel_id is not None:
            return current.channel_id
        if current.parent_session_id is None:
            return None
        current = await db.get(Session, current.parent_session_id)
        depth += 1
    return None
