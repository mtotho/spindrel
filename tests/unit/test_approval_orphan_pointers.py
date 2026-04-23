"""Approval-state creation seam tests for ``dispatch_tool_call``.

The approval gate must create the awaiting-approval ``ToolCall`` row and the
pending ``ToolApproval`` row together. If that creation fails, the dispatcher
must not leak a dangling approval pointer or pretend the tool is now waiting on
human input.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agent.tool_dispatch import dispatch_tool_call
from app.db.models import ToolApproval, ToolCall

pytestmark = pytest.mark.asyncio


def _kw(**overrides) -> dict:
    base = dict(
        args="{}",
        tool_call_id="tc_1",
        bot_id="approval-seam-bot",
        bot_memory=None,
        session_id=uuid.uuid4(),
        client_id="test-client",
        correlation_id=uuid.uuid4(),
        channel_id=None,
        iteration=0,
        provider_id=None,
        summarize_enabled=False,
        summarize_threshold=10000,
        summarize_model="test/model",
        summarize_max_tokens=500,
        summarize_exclude=set(),
        compaction=False,
    )
    base.update(overrides)
    return base


def _approval_decision(reason: str = "needs review", timeout: int = 300) -> MagicMock:
    decision = MagicMock()
    decision.action = "require_approval"
    decision.reason = reason
    decision.rule_id = None
    decision.tier = None
    decision.timeout = timeout
    return decision


class TestApprovalStateCreation:
    async def test_when_creation_succeeds_then_both_rows_exist_and_linked(
        self, db_session, patched_async_sessions
    ):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch(
                 "app.agent.tool_dispatch._check_tool_policy",
                 new_callable=AsyncMock,
                 return_value=_approval_decision(),
             ):
            result = await dispatch_tool_call(
                name="write_file", allowed_tool_names=None, **_kw()
            )

        tc_row = (await db_session.execute(select(ToolCall))).scalar_one()
        approval_row = (await db_session.execute(select(ToolApproval))).scalar_one()

        assert result.needs_approval is True
        assert result.record_id == tc_row.id
        assert result.approval_id == str(approval_row.id)
        assert tc_row.status == "awaiting_approval"
        assert approval_row.status == "pending"
        assert approval_row.tool_call_id == tc_row.id

    async def test_when_atomic_create_fails_then_no_rows_are_committed(
        self, db_session, patched_async_sessions
    ):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch(
                 "app.agent.tool_dispatch._check_tool_policy",
                 new_callable=AsyncMock,
                 return_value=_approval_decision("exec tier", timeout=120),
             ), \
             patch(
                 "app.agent.tool_dispatch._create_approval_state",
                 new_callable=AsyncMock,
                 side_effect=RuntimeError("DB pool exhausted"),
             ):
            result = await dispatch_tool_call(
                name="exec_cmd", allowed_tool_names=None, **_kw()
            )

        approval_rows = (await db_session.execute(select(ToolApproval))).scalars().all()
        tool_call_rows = (await db_session.execute(select(ToolCall))).scalars().all()

        assert approval_rows == []
        assert tool_call_rows == []
        assert result.needs_approval is False
        assert result.approval_id is None
        assert result.record_id is None
        assert "approval state could not be created" in (result.result or "")
