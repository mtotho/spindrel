"""Phase E.9 — multi-actor seam: multi-bot snapshot + decide non-primary

Extends the Phase D snapshot tests (test_channel_state_snapshot.py) with
scenarios where BOTH the primary bot and one or more non-primary bots have
active turns at the same time. Pins:

1. Both turns surface — snapshot doesn't drop non-primary bot activity.
2. Primary is sorted first in the returned list.
3. A non-primary bot's awaiting_approval ToolCall links to its ToolApproval
   row even when is_primary=False — the per-bot isolation in
   ``_snapshot_active_turns`` must not filter out non-primary approvals.
4. Completing the primary turn (terminal assistant message) removes it from
   the snapshot while the non-primary turn remains visible.
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel, Message, Session, ToolApproval, ToolCall
from app.routers.api_v1_channels import get_channel_state

pytestmark = pytest.mark.asyncio

PRIMARY_BOT = "primary-bot"
SECONDARY_BOT = "helper-bot"


async def _seed_channel(db_session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert Channel + Session bound to PRIMARY_BOT. Returns (channel_id, session_id)."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Session(
        id=session_id,
        client_id="test",
        bot_id=PRIMARY_BOT,
        channel_id=channel_id,
    ))
    db_session.add(Channel(
        id=channel_id,
        name=f"ch-{channel_id.hex[:6]}",
        bot_id=PRIMARY_BOT,
        active_session_id=session_id,
    ))
    await db_session.commit()
    return channel_id, session_id


class TestMultiBotConcurrentTurns:
    async def test_primary_and_nonprimary_turns_both_surface(self, db_session):
        """When both bots have in-flight ToolCalls they must both appear in
        active_turns — the snapshot must not silently drop non-primary activity."""
        channel_id, session_id = await _seed_channel(db_session)
        primary_corr = uuid.uuid4()
        secondary_corr = uuid.uuid4()

        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id=PRIMARY_BOT,
            tool_name="read_file",
            tool_type="local",
            arguments={},
            correlation_id=primary_corr,
            status="running",
        ))
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id=SECONDARY_BOT,
            tool_name="web_search",
            tool_type="local",
            arguments={},
            correlation_id=secondary_corr,
            status="running",
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        corr_ids = {t.turn_id for t in out.active_turns}
        assert primary_corr in corr_ids
        assert secondary_corr in corr_ids

    async def test_primary_bot_sorted_before_nonprimary(self, db_session):
        """``_snapshot_active_turns`` sorts primary first. The channel bot's
        turn must appear at index 0 regardless of insertion order."""
        channel_id, session_id = await _seed_channel(db_session)
        secondary_corr = uuid.uuid4()
        primary_corr = uuid.uuid4()

        # Insert secondary first to stress the sort.
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id=SECONDARY_BOT,
            tool_name="web_search",
            tool_type="local",
            arguments={},
            correlation_id=secondary_corr,
            status="running",
        ))
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id=PRIMARY_BOT,
            tool_name="read_file",
            tool_type="local",
            arguments={},
            correlation_id=primary_corr,
            status="running",
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.active_turns) == 2
        assert out.active_turns[0].is_primary is True
        assert out.active_turns[0].turn_id == primary_corr
        assert out.active_turns[1].is_primary is False
        assert out.active_turns[1].turn_id == secondary_corr

    async def test_nonprimary_awaiting_approval_links_to_approval_row(self, db_session):
        """A non-primary bot's ``awaiting_approval`` ToolCall must link to its
        ToolApproval row just as a primary bot's would. The is_primary=False
        attribute must not prevent approval_id or approval_reason from populating."""
        channel_id, session_id = await _seed_channel(db_session)
        tc_id = uuid.uuid4()
        approval_id = uuid.uuid4()
        secondary_corr = uuid.uuid4()

        db_session.add(ToolCall(
            id=tc_id,
            session_id=session_id,
            bot_id=SECONDARY_BOT,
            tool_name="write_file",
            tool_type="local",
            arguments={"path": "/x"},
            correlation_id=secondary_corr,
            status="awaiting_approval",
        ))
        db_session.add(ToolApproval(
            id=approval_id,
            session_id=session_id,
            channel_id=channel_id,
            bot_id=SECONDARY_BOT,
            correlation_id=secondary_corr,
            tool_name="write_file",
            tool_type="local",
            arguments={"path": "/x"},
            reason="non-primary policy gate",
            status="pending",
            tool_call_id=tc_id,
            timeout_seconds=300,
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.active_turns) == 1
        turn = out.active_turns[0]
        assert turn.is_primary is False
        tc = turn.tool_calls[0]
        assert tc.status == "awaiting_approval"
        assert tc.approval_id == approval_id
        assert tc.approval_reason == "non-primary policy gate"

    async def test_primary_turn_completion_leaves_nonprimary_active(self, db_session):
        """When the primary bot's correlation_id gets a terminal assistant
        message it is excluded from the snapshot. The non-primary bot's turn,
        which has no terminal message, must remain visible."""
        channel_id, session_id = await _seed_channel(db_session)
        primary_corr = uuid.uuid4()
        secondary_corr = uuid.uuid4()

        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id=PRIMARY_BOT,
            tool_name="read_file",
            tool_type="local",
            arguments={},
            correlation_id=primary_corr,
            status="done",
        ))
        db_session.add(Message(
            id=uuid.uuid4(),
            session_id=session_id,
            role="assistant",
            content="done",
            correlation_id=primary_corr,
        ))
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id=SECONDARY_BOT,
            tool_name="web_search",
            tool_type="local",
            arguments={},
            correlation_id=secondary_corr,
            status="running",
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.active_turns) == 1
        turn = out.active_turns[0]
        assert turn.turn_id == secondary_corr
        assert turn.is_primary is False

    async def test_is_primary_false_when_bot_id_not_channel_bot(self, db_session):
        """Explicit is_primary check: a secondary bot's turn has is_primary=False
        and the primary bot's own turn has is_primary=True."""
        channel_id, session_id = await _seed_channel(db_session)
        primary_corr = uuid.uuid4()
        secondary_corr = uuid.uuid4()

        for bot, corr in [(PRIMARY_BOT, primary_corr), (SECONDARY_BOT, secondary_corr)]:
            db_session.add(ToolCall(
                id=uuid.uuid4(),
                session_id=session_id,
                bot_id=bot,
                tool_name="tool",
                tool_type="local",
                arguments={},
                correlation_id=corr,
                status="running",
            ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        by_corr = {t.turn_id: t for t in out.active_turns}
        assert by_corr[primary_corr].is_primary is True
        assert by_corr[secondary_corr].is_primary is False
