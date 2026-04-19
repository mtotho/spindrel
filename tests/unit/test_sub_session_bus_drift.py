"""Phase G.1 — sub_session_bus::resolve_bus_channel_id drift seams.

Seam class: multi-row sync + orphan pointer

The existing test_sub_session_bus_bridge.py covers happy paths (walk,
orphan, missing). This file pins the safety-guard contracts:

1. Cycle detection — A→B→A chain returns None, not infinite loop.
2. Self-reference cycle — session.parent_session_id = self.id.
3. Depth limit — 16-level chain without a channel_id exhausts MAX_WALK_DEPTH.
4. Chain found just inside depth limit — channel_id at depth=15 is returned.
5. Mid-walk deletion — intermediate session missing from DB; graceful None.

Drift risk: silently returns a stale channel_id or spins if cycle
detection or depth guard is removed.
"""
from __future__ import annotations

import logging
import uuid

import pytest

from app.db.models import Channel, Session
from app.services.sub_session_bus import MAX_WALK_DEPTH, resolve_bus_channel_id


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _make_channel(db: AsyncSession) -> Channel:
    ch = Channel(
        id=uuid.uuid4(),
        client_id="web",
        bot_id="b",
        name="test",
    )
    db.add(ch)
    await db.flush()
    return ch


async def _make_session(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID | None = None,
    parent_session_id: uuid.UUID | None = None,
) -> Session:
    s = Session(
        id=uuid.uuid4(),
        client_id="web" if channel_id else "task",
        bot_id="b",
        channel_id=channel_id,
        parent_session_id=parent_session_id,
        depth=0,
        session_type="channel" if channel_id else "pipeline_run",
    )
    db.add(s)
    await db.flush()
    return s


# ---------------------------------------------------------------------------
# G.1.1 — cycle detection (A → B → A)
# ---------------------------------------------------------------------------


class TestCycleDetection:
    @pytest.mark.asyncio
    async def test_two_node_cycle_returns_none(self, db_session, caplog):
        """A→B→A chain is detected; returns None + logs a warning."""
        # Create both sessions without parent links first, then set them.
        s_a = await _make_session(db_session)
        s_b = await _make_session(db_session)

        # Wire the cycle: A → B → A
        s_a.parent_session_id = s_b.id
        s_b.parent_session_id = s_a.id
        await db_session.flush()

        with caplog.at_level(logging.WARNING):
            result = await resolve_bus_channel_id(db_session, s_a.id)

        assert result is None
        assert "cycle" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_self_reference_cycle_returns_none(self, db_session):
        """session.parent_session_id = self.id is a degenerate cycle."""
        s = await _make_session(db_session)
        s.parent_session_id = s.id
        await db_session.flush()

        result = await resolve_bus_channel_id(db_session, s.id)
        assert result is None


# ---------------------------------------------------------------------------
# G.1.2 — depth limit
# ---------------------------------------------------------------------------


class TestDepthLimit:
    @pytest.mark.asyncio
    async def test_chain_exhausts_max_depth_returns_none(self, db_session):
        """A chain longer than MAX_WALK_DEPTH with no channel_id returns None."""
        # Build MAX_WALK_DEPTH + 1 sub-sessions; the channel would be at the tip.
        channel = await _make_channel(db_session)
        channel_session = await _make_session(db_session, channel_id=channel.id)

        # Stack MAX_WALK_DEPTH sub-sessions on top — the resolver hits depth >= 16
        # before it reaches the channel session.
        parent_id = channel_session.id
        for _ in range(MAX_WALK_DEPTH):
            s = await _make_session(db_session, parent_session_id=parent_id)
            parent_id = s.id
        leaf_id = parent_id

        result = await resolve_bus_channel_id(db_session, leaf_id)
        assert result is None, (
            "Chain deeper than MAX_WALK_DEPTH must return None — "
            "never reach the channel session"
        )

    @pytest.mark.asyncio
    async def test_chain_just_inside_depth_limit_returns_channel(self, db_session):
        """A chain exactly MAX_WALK_DEPTH - 1 levels deep still resolves."""
        channel = await _make_channel(db_session)
        channel_session = await _make_session(db_session, channel_id=channel.id)

        # MAX_WALK_DEPTH - 1 sub-sessions on top (one level to spare).
        parent_id = channel_session.id
        for _ in range(MAX_WALK_DEPTH - 1):
            s = await _make_session(db_session, parent_session_id=parent_id)
            parent_id = s.id
        leaf_id = parent_id

        result = await resolve_bus_channel_id(db_session, leaf_id)
        assert result == channel.id


# ---------------------------------------------------------------------------
# G.1.3 — mid-walk deletion (orphan pointer)
# ---------------------------------------------------------------------------


class TestMidWalkDeletion:
    @pytest.mark.asyncio
    async def test_missing_parent_session_returns_none(self, db_session):
        """parent_session_id pointing at a non-existent row → graceful None.

        This pins the db.get-returns-None path in the walk loop. The FK
        is ``ondelete=SET NULL`` on sessions.parent_session_id, so once the
        parent is gone the child's parent_session_id becomes NULL — the walk
        resolves None either way (NULL parent or missing parent).

        We test the missing-row variant directly: create a sub-session whose
        parent_session_id points to a UUID that was never inserted.
        """
        ghost_id = uuid.uuid4()  # never inserted → db.get returns None
        leaf = await _make_session(db_session, parent_session_id=ghost_id)
        await db_session.flush()

        result = await resolve_bus_channel_id(db_session, leaf.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_chain_with_null_parent_link_returns_none(self, db_session):
        """A sub-session that has no parent (orphan) is the documented None path."""
        orphan = await _make_session(db_session)  # channel_id=None, parent=None
        await db_session.flush()

        result = await resolve_bus_channel_id(db_session, orphan.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_session_id_returns_none_immediately(self, db_session):
        """resolve_bus_channel_id(db, None) returns None without a DB query."""
        result = await resolve_bus_channel_id(db_session, None)
        assert result is None
