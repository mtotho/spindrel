"""Unit tests for app.agent.context — ContextVar management."""
import uuid

import pytest

from app.agent.context import (
    current_bot_id,
    current_client_id,
    current_ephemeral_delegates,
    current_memory_cross_channel,
    current_session_depth,
    current_session_id,
    restore_agent_context,
    set_agent_context,
    set_ephemeral_delegates,
    snapshot_agent_context,
)


@pytest.mark.asyncio
class TestSetAgentContext:
    async def test_sets_core_vars(self):
        sid = uuid.uuid4()
        set_agent_context(session_id=sid, client_id="c1", bot_id="bot1")
        assert current_session_id.get() == sid
        assert current_client_id.get() == "c1"
        assert current_bot_id.get() == "bot1"

    async def test_only_sets_memory_when_not_none(self):
        # Reset to known state
        current_memory_cross_channel.set(None)
        set_agent_context(session_id=None, client_id=None, bot_id=None)
        # memory_cross_channel should stay None (not overwritten)
        assert current_memory_cross_channel.get() is None

        set_agent_context(
            session_id=None, client_id=None, bot_id=None,
            memory_cross_channel=True,
        )
        assert current_memory_cross_channel.get() is True

    async def test_only_sets_depth_when_not_none(self):
        current_session_depth.set(0)
        set_agent_context(session_id=None, client_id=None, bot_id=None)
        assert current_session_depth.get() == 0

        set_agent_context(
            session_id=None, client_id=None, bot_id=None,
            session_depth=5,
        )
        assert current_session_depth.get() == 5


@pytest.mark.asyncio
class TestSnapshotRestore:
    async def test_round_trip(self):
        sid = uuid.uuid4()
        set_agent_context(
            session_id=sid, client_id="c1", bot_id="bot1",
            memory_cross_channel=True, session_depth=3,
        )
        snap = snapshot_agent_context()
        assert snap.session_id == sid
        assert snap.client_id == "c1"
        assert snap.bot_id == "bot1"
        assert snap.memory_cross_channel is True
        assert snap.session_depth == 3

        # Change context
        set_agent_context(session_id=None, client_id="c2", bot_id="bot2")

        # Restore
        restore_agent_context(snap)
        assert current_session_id.get() == sid
        assert current_client_id.get() == "c1"
        assert current_bot_id.get() == "bot1"

    async def test_snapshot_is_a_copy(self):
        set_ephemeral_delegates(["a", "b"])
        snap = snapshot_agent_context()
        # Mutating snapshot should not affect live vars
        snap.ephemeral_delegates.append("c")
        assert "c" not in current_ephemeral_delegates.get()


@pytest.mark.asyncio
class TestSetEphemeralDelegates:
    async def test_set_and_get(self):
        set_ephemeral_delegates(["bot_a", "bot_b"])
        assert current_ephemeral_delegates.get() == ["bot_a", "bot_b"]

    async def test_creates_copy(self):
        original = ["bot_a"]
        set_ephemeral_delegates(original)
        original.append("bot_b")
        assert current_ephemeral_delegates.get() == ["bot_a"]
