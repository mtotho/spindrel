"""Phase 3 — snapshot endpoint (``GET /api/v1/channels/{id}/state``).

Contract the UI relies on when rehydrating chat state on mount, tab-wake, or
SSE ``replay_lapsed``:

1. An in-flight ``ToolCall`` (status ``running`` / ``awaiting_approval``)
   inside the active-turn window surfaces as an ``active_turns`` entry —
   without it, the orphan approval card and streaming-tool chip both
   disappear on refresh.
2. A correlation_id that already produced a terminal assistant ``Message``
   is excluded — that turn is done; surfacing it would double-render the
   finished exchange.
3. ``pending`` ``ToolApproval`` rows for the channel come back in
   ``pending_approvals`` so the orphan-approval section keeps working
   without a second REST call.
4. ``TraceEvent(event_type='skill_index')`` with an ``auto_injected`` list
   rehydrates the per-skill chips; names are resolved via the ``Skill``
   table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import (
    Channel,
    Message,
    Session,
    Skill,
    ToolApproval,
    ToolCall,
    TraceEvent,
)
from app.routers.api_v1_channels import get_channel_state


pytestmark = pytest.mark.asyncio


async def _seed_channel(db_session, *, bot_id: str = "test-bot") -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a Channel bound to a fresh Session and return (channel_id, session_id)."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Session(
        id=session_id,
        client_id="test",
        bot_id=bot_id,
        channel_id=channel_id,
    ))
    db_session.add(Channel(
        id=channel_id,
        name=f"ch-{channel_id.hex[:6]}",
        bot_id=bot_id,
        active_session_id=session_id,
    ))
    await db_session.commit()
    return channel_id, session_id


class TestActiveTurnSurfacing:
    async def test_running_tool_call_surfaces_as_active_turn(self, db_session):
        channel_id, session_id = await _seed_channel(db_session)
        correlation_id = uuid.uuid4()
        tc_id = uuid.uuid4()
        db_session.add(ToolCall(
            id=tc_id,
            session_id=session_id,
            bot_id="test-bot",
            tool_name="read_file",
            tool_type="local",
            arguments={"path": "/x"},
            correlation_id=correlation_id,
            status="running",
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.active_turns) == 1
        turn = out.active_turns[0]
        assert turn.turn_id == correlation_id
        assert turn.bot_id == "test-bot"
        assert turn.is_primary is True
        assert len(turn.tool_calls) == 1
        tc = turn.tool_calls[0]
        assert tc.tool_name == "read_file"
        assert tc.status == "running"
        assert tc.approval_id is None

    async def test_awaiting_approval_tool_call_exposes_linked_approval(self, db_session):
        channel_id, session_id = await _seed_channel(db_session)
        correlation_id = uuid.uuid4()
        tc_id = uuid.uuid4()
        approval_id = uuid.uuid4()
        db_session.add(ToolCall(
            id=tc_id,
            session_id=session_id,
            bot_id="test-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={"path": "/x"},
            correlation_id=correlation_id,
            status="awaiting_approval",
        ))
        db_session.add(ToolApproval(
            id=approval_id,
            session_id=session_id,
            channel_id=channel_id,
            bot_id="test-bot",
            correlation_id=correlation_id,
            tool_name="write_file",
            tool_type="local",
            arguments={"path": "/x"},
            reason="policy gate",
            status="pending",
            tool_call_id=tc_id,
            approval_metadata={"_capability": {
                "id": "cap-1", "name": "file ops",
                "description": "write files", "tools_count": 3, "skills_count": 0,
            }},
            timeout_seconds=300,
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.active_turns) == 1
        tc = out.active_turns[0].tool_calls[0]
        assert tc.status == "awaiting_approval"
        assert tc.approval_id == approval_id
        assert tc.approval_reason == "policy gate"
        assert tc.capability is not None
        assert tc.capability["name"] == "file ops"

    async def test_terminal_assistant_message_excludes_completed_turn(self, db_session):
        channel_id, session_id = await _seed_channel(db_session)
        correlation_id = uuid.uuid4()
        # Old completed turn: has a ToolCall AND a terminal assistant message.
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id="test-bot",
            tool_name="read_file",
            tool_type="local",
            arguments={},
            correlation_id=correlation_id,
            status="done",
        ))
        db_session.add(Message(
            id=uuid.uuid4(),
            session_id=session_id,
            role="assistant",
            content="done",
            correlation_id=correlation_id,
        ))
        # Fresh turn: no terminal message → should surface.
        live_corr = uuid.uuid4()
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id="test-bot",
            tool_name="grep",
            tool_type="local",
            arguments={},
            correlation_id=live_corr,
            status="running",
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert [t.turn_id for t in out.active_turns] == [live_corr]

    async def test_tool_call_outside_window_is_ignored(self, db_session):
        """Stale correlation_ids from hours-old activity must not surface as 'active'."""
        channel_id, session_id = await _seed_channel(db_session)
        stale = uuid.uuid4()
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id="test-bot",
            tool_name="read_file",
            tool_type="local",
            arguments={},
            correlation_id=stale,
            status="running",  # status doesn't save it — it's just too old
            created_at=old,
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)
        assert out.active_turns == []


class TestMultiBotAndOrphans:
    async def test_foreign_bot_turn_is_not_primary(self, db_session):
        """A turn emitted by a bot that isn't the channel's own bot must have is_primary=False.

        Without this distinction the UI collapses every bot's tool calls into
        the channel-bot's turn card and loses the multi-bot routing affordances.
        """
        channel_id, session_id = await _seed_channel(db_session, bot_id="rolland")
        correlation_id = uuid.uuid4()
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id="helper-bot",  # NOT the channel bot
            tool_name="read_file",
            tool_type="local",
            arguments={},
            correlation_id=correlation_id,
            status="running",
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.active_turns) == 1
        turn = out.active_turns[0]
        assert turn.bot_id == "helper-bot"
        assert turn.is_primary is False

    async def test_awaiting_approval_without_matching_approval_row_surfaces_orphan(
        self, db_session,
    ):
        """ToolCall=awaiting_approval with no ToolApproval row → approval_id=None.

        Can happen if the approval row was never inserted (dispatch race where
        ``_start_tool_call`` committed first and ``_create_approval_record``
        failed after) or was deleted manually. The snapshot still surfaces the
        ToolCall so the UI renders an approval card — but without an
        approval_id the card is undecidable until the 10-min window expires.
        Pins this as a visible-but-stuck contract.
        """
        channel_id, session_id = await _seed_channel(db_session)
        correlation_id = uuid.uuid4()
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id="test-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={},
            correlation_id=correlation_id,
            status="awaiting_approval",
        ))
        # No matching ToolApproval insert — that's the orphan case.
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        tc = out.active_turns[0].tool_calls[0]
        assert tc.status == "awaiting_approval"
        assert tc.approval_id is None
        assert tc.approval_reason is None


class TestPendingApprovalsInSnapshot:
    async def test_pending_approvals_return_for_channel(self, db_session):
        channel_id, session_id = await _seed_channel(db_session)
        other_channel = uuid.uuid4()
        db_session.add(ToolApproval(
            id=uuid.uuid4(),
            session_id=session_id,
            channel_id=channel_id,
            bot_id="test-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={},
            status="pending",
            timeout_seconds=300,
        ))
        # Different channel → must NOT appear.
        db_session.add(ToolApproval(
            id=uuid.uuid4(),
            channel_id=other_channel,
            bot_id="test-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={},
            status="pending",
            timeout_seconds=300,
        ))
        # Already-decided in the current channel → must NOT appear.
        db_session.add(ToolApproval(
            id=uuid.uuid4(),
            channel_id=channel_id,
            bot_id="test-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={},
            status="approved",
            timeout_seconds=300,
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.pending_approvals) == 1
        assert out.pending_approvals[0]["status"] == "pending"
        assert out.pending_approvals[0]["channel_id"] == str(channel_id)


class TestSkillAutoInjectRehydration:
    async def test_auto_injected_skill_ids_become_named_chips(self, db_session):
        channel_id, session_id = await _seed_channel(db_session)
        correlation_id = uuid.uuid4()
        # A live ToolCall so the correlation_id qualifies as an active turn.
        db_session.add(ToolCall(
            id=uuid.uuid4(),
            session_id=session_id,
            bot_id="test-bot",
            tool_name="read_file",
            tool_type="local",
            arguments={},
            correlation_id=correlation_id,
            status="running",
        ))
        db_session.add(Skill(
            id="skill-a",
            name="Slack conversation hygiene",
            content="",
            content_hash="h1",
        ))
        db_session.add(TraceEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id="test-bot",
            event_type="skill_index",
            count=2,
            data={
                "auto_injected": ["skill-a", "skill-missing"],
                "ranking_scores": [
                    {"skill_id": "skill-a", "similarity": 0.74},
                    {"skill_id": "skill-missing", "similarity": 0.55},
                ],
            },
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)

        assert len(out.active_turns) == 1
        skills = out.active_turns[0].auto_injected_skills
        assert {s.skill_id for s in skills} == {"skill-a", "skill-missing"}
        named = {s.skill_id: s for s in skills}
        assert named["skill-a"].skill_name == "Slack conversation hygiene"
        # Unknown skill id falls back to the id so the chip still renders.
        assert named["skill-missing"].skill_name == "skill-missing"
        assert named["skill-a"].similarity == 0.74


class TestEmptyStateCases:
    async def test_channel_without_active_session_returns_empty(self, db_session):
        channel_id = uuid.uuid4()
        db_session.add(Channel(
            id=channel_id,
            name="no-session",
            bot_id="test-bot",
            active_session_id=None,
        ))
        await db_session.commit()

        out = await get_channel_state(channel_id=channel_id, db=db_session, _auth=None)
        assert out.active_turns == []
        assert out.pending_approvals == []

    async def test_missing_channel_is_404(self, db_session):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await get_channel_state(
                channel_id=uuid.uuid4(), db=db_session, _auth=None,
            )
        assert exc.value.status_code == 404
