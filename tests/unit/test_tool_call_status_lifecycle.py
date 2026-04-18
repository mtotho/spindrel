"""Tests for the ToolCall status lifecycle introduced in Phase 2 of
the chat-state-rehydration track (migration 207).

Three behaviors covered:

1. ``_start_tool_call`` writes a ``status='running'`` row up front; the
   subsequent ``_complete_tool_call`` UPDATEs the same row id to a
   terminal state and stamps ``completed_at`` — the chat UI snapshot
   endpoint can therefore find an in-flight tool *before* it returns.
2. The approval decide endpoint flips a linked
   ``status='awaiting_approval'`` ToolCall to ``'running'`` on approve
   and ``'denied'`` on deny — orphan cards rehydrated post-decision
   reflect the final state.
3. ``_record_trace_event`` persists an ``event_type='skill_index'`` row
   with the ``auto_injected`` payload — the same row Phase 3's snapshot
   endpoint will later read for skill-injection cards.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agent.recording import (
    _complete_tool_call,
    _record_trace_event,
    _start_tool_call,
)
from app.db.models import ToolApproval, ToolCall, TraceEvent
from app.routers.api_v1_approvals import DecideRequest, decide_approval


pytestmark = pytest.mark.asyncio


class TestToolCallStatusLifecycle:
    async def test_start_writes_running_row_and_complete_flips_to_done(
        self, db_session, patched_async_sessions,
    ):
        """The row must exist in 'running' BEFORE completion — that's the
        whole point of Phase 2 (Phase 3 reads from this row to rehydrate
        in-flight chat state on refresh)."""
        row_id = uuid.uuid4()
        bot_id = "test-bot"
        correlation_id = uuid.uuid4()

        await _start_tool_call(
            id=row_id,
            session_id=None,
            client_id=None,
            bot_id=bot_id,
            tool_name="read_file",
            tool_type="local",
            server_name=None,
            iteration=0,
            arguments={"path": "/tmp/x"},
            correlation_id=correlation_id,
        )

        running_row = (
            await db_session.execute(select(ToolCall).where(ToolCall.id == row_id))
        ).scalar_one()
        assert running_row.status == "running"
        assert running_row.completed_at is None
        assert running_row.result is None
        assert running_row.duration_ms is None
        assert running_row.arguments == {"path": "/tmp/x"}

        await _complete_tool_call(
            row_id,
            result='{"content": "hello"}',
            error=None,
            duration_ms=42,
            status="done",
        )

        db_session.expire_all()
        done_row = (
            await db_session.execute(select(ToolCall).where(ToolCall.id == row_id))
        ).scalar_one()
        assert done_row.id == row_id
        assert done_row.status == "done"
        assert done_row.result == '{"content": "hello"}'
        assert done_row.duration_ms == 42
        assert done_row.completed_at is not None
        assert done_row.completed_at >= done_row.created_at

    async def test_complete_with_error_marks_status_error(
        self, db_session, patched_async_sessions,
    ):
        row_id = uuid.uuid4()
        await _start_tool_call(
            id=row_id,
            session_id=None,
            client_id=None,
            bot_id="bot",
            tool_name="grep",
            tool_type="local",
            server_name=None,
            iteration=0,
            arguments={},
            correlation_id=None,
        )

        await _complete_tool_call(
            row_id, result='{"error": "boom"}', error="boom", duration_ms=5, status="error",
        )

        db_session.expire_all()
        row = (
            await db_session.execute(select(ToolCall).where(ToolCall.id == row_id))
        ).scalar_one()
        assert row.status == "error"
        assert row.error == "boom"


class TestApprovalTransitionsToolCallStatus:
    """The decide endpoint must keep the linked ToolCall row in lockstep
    with the ToolApproval verdict — orphan cards rehydrated post-decision
    show the final state, never 'awaiting_approval' frozen forever."""

    async def _seed(self, db_session, *, approved: bool):
        tc_id = uuid.uuid4()
        approval_id = uuid.uuid4()
        bot_id = "test-bot"
        now = datetime.now(timezone.utc)

        db_session.add(ToolCall(
            id=tc_id,
            session_id=None,
            client_id=None,
            bot_id=bot_id,
            tool_name="write_file",
            tool_type="local",
            server_name=None,
            iteration=0,
            arguments={"path": "/x"},
            result=None,
            error=None,
            duration_ms=None,
            correlation_id=None,
            created_at=now,
            status="awaiting_approval",
            completed_at=None,
        ))
        db_session.add(ToolApproval(
            id=approval_id,
            session_id=None,
            channel_id=None,
            bot_id=bot_id,
            client_id=None,
            correlation_id=None,
            tool_name="write_file",
            tool_type="local",
            arguments={"path": "/x"},
            policy_rule_id=None,
            reason="autonomous default",
            status="pending",
            decided_by=None,
            decided_at=None,
            dispatch_type=None,
            dispatch_metadata=None,
            approval_metadata=None,
            tool_call_id=tc_id,
            timeout_seconds=300,
            created_at=now,
        ))
        await db_session.commit()
        return approval_id, tc_id

    async def test_approve_flips_tool_call_status_to_running(
        self, db_session, patched_async_sessions, monkeypatch,
    ):
        approval_id, tc_id = await self._seed(db_session, approved=True)

        monkeypatch.setattr(
            "app.agent.approval_pending.resolve_approval", lambda aid, v: True,
        )
        monkeypatch.setattr(
            "app.agent.session_allows.add_session_allow", lambda *a, **k: None,
        )

        await decide_approval(
            approval_id=approval_id,
            body=DecideRequest(approved=True, decided_by="user"),
            _auth=None,
            db=db_session,
        )

        db_session.expire_all()
        tc_row = (
            await db_session.execute(select(ToolCall).where(ToolCall.id == tc_id))
        ).scalar_one()
        assert tc_row.status == "running"
        # completed_at is intentionally not stamped on approve — the
        # post-approval re-dispatch stamps it on actual completion.
        assert tc_row.completed_at is None

    async def test_deny_flips_tool_call_status_to_denied(
        self, db_session, patched_async_sessions, monkeypatch,
    ):
        approval_id, tc_id = await self._seed(db_session, approved=False)

        monkeypatch.setattr(
            "app.agent.approval_pending.resolve_approval", lambda aid, v: True,
        )

        await decide_approval(
            approval_id=approval_id,
            body=DecideRequest(approved=False, decided_by="user"),
            _auth=None,
            db=db_session,
        )

        db_session.expire_all()
        tc_row = (
            await db_session.execute(select(ToolCall).where(ToolCall.id == tc_id))
        ).scalar_one()
        assert tc_row.status == "denied"
        assert tc_row.completed_at is not None


class TestSkillAutoInjectTraceEvent:
    """The auto-inject TraceEvent is what Phase 3's snapshot endpoint reads
    to render the 'auto-injected skill X' card on a refreshed channel.
    Confirm the row is queryable by ``correlation_id`` + ``event_type``."""

    async def test_skill_index_trace_event_is_persisted_and_queryable(
        self, db_session, patched_async_sessions,
    ):
        correlation_id = uuid.uuid4()
        bot_id = "test-bot"

        await _record_trace_event(
            correlation_id=correlation_id,
            session_id=None,
            bot_id=bot_id,
            client_id=None,
            event_type="skill_index",
            event_name=None,
            count=2,
            data={
                "auto_injected": ["skill-a", "skill-b"],
                "ranked_relevant": ["skill-a", "skill-b", "skill-c"],
            },
        )

        rows = (await db_session.execute(
            select(TraceEvent).where(
                TraceEvent.correlation_id == correlation_id,
                TraceEvent.event_type == "skill_index",
            )
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].bot_id == bot_id
        assert rows[0].count == 2
        assert rows[0].data["auto_injected"] == ["skill-a", "skill-b"]
