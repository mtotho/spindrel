"""Phase E.3 drift-seam test: tool_dispatch approval-create race.

Seam class: background-task ordering + orphan pointer.

Both approval-gate paths in dispatch_tool_call share the same ordering:

    safe_create_task(_start_tool_call(id=pending_id, status='awaiting_approval'))
    approval_id = await _create_approval_record(..., tool_call_id=pending_id)

ToolApproval commits synchronously; ToolCall lands asynchronously. If
_start_tool_call raises (DB error, pool exhaustion, etc.) the ToolApproval
commits with a tool_call_id that references a non-existent ToolCall — a ghost
pointer the snapshot endpoint and decide endpoint must handle gracefully.

Phase D coverage for downstream consequences:
  test_channel_state_snapshot.py — ToolCall awaiting_approval with no matching
    ToolApproval (inverse direction; approval_id=None surfaced in snapshot)
  test_decide_approval_flow.py — decide when tool_call_id=None: only the
    ToolApproval row is flipped (test_when_tool_call_id_none_*)
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agent.tool_dispatch import dispatch_tool_call
from app.db.models import ToolApproval, ToolCall

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kw(**overrides) -> dict:
    """Minimal kwargs for dispatch_tool_call. channel_id=None avoids
    the _notify_approval_request fire-and-forget in the approval path."""
    base = dict(
        args="{}",
        tool_call_id="tc_1",
        bot_id="e3-test-bot",
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
    d = MagicMock()
    d.action = "require_approval"
    d.reason = reason
    d.rule_id = None
    d.tier = None
    d.timeout = timeout
    return d


async def _flush(n: int = 5) -> None:
    """Yield to the event loop n times so fire-and-forget tasks can land."""
    for _ in range(n):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Policy-gate path (tool_dispatch.py:367-393)
# ---------------------------------------------------------------------------

class TestPolicyGateHappyPath:
    async def test_when_start_completes_then_both_rows_exist_and_linked(
        self, db_session, patched_async_sessions
    ):
        """Normal ordering: ToolApproval commits synchronously, then the
        background _start_tool_call task inserts the ToolCall. After flush
        both rows exist and ToolApproval.tool_call_id == ToolCall.id.
        """
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_approval_decision()):
            await dispatch_tool_call(name="write_file", allowed_tool_names=None, **_kw())

        await _flush()
        db_session.expire_all()

        tc_rows = (await db_session.execute(select(ToolCall))).scalars().all()
        ap_rows = (await db_session.execute(select(ToolApproval))).scalars().all()
        assert len(tc_rows) == 1
        assert len(ap_rows) == 1
        assert tc_rows[0].status == "awaiting_approval"
        assert ap_rows[0].tool_call_id == tc_rows[0].id

    async def test_result_record_id_matches_toolcall_row_id(
        self, db_session, patched_async_sessions
    ):
        """result.record_id is the pre-allocated UUID — loop.py uses it as
        existing_record_id to UPDATE the same row on re-dispatch."""
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_approval_decision()):
            result = await dispatch_tool_call(
                name="exec_cmd", allowed_tool_names=None, **_kw()
            )

        await _flush()
        db_session.expire_all()

        tc_row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert result.record_id == tc_row.id


class TestPolicyGateOrphanPointer:
    async def test_when_start_tool_call_raises_then_approval_commits_with_ghost_id(
        self, db_session, patched_async_sessions
    ):
        """Drift pin: if _start_tool_call's background task fails, ToolApproval
        is already committed but ToolCall never lands. ToolApproval.tool_call_id
        holds the pre-allocated UUID that points at no row.

        Downstream: decide_approval sees tool_call_id=<ghost>; SELECT ToolCall
        WHERE id=<ghost> returns None, so only the ToolApproval row gets flipped
        (pinned in test_decide_approval_flow.py::test_when_tool_call_id_none_*).
        """
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_approval_decision()), \
             patch("app.agent.tool_dispatch._start_tool_call",
                   new_callable=AsyncMock,
                   side_effect=RuntimeError("DB pool exhausted")):
            result = await dispatch_tool_call(
                name="write_file", allowed_tool_names=None, **_kw()
            )

        await _flush()
        db_session.expire_all()

        tc_rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(tc_rows) == 0

        ap_rows = (await db_session.execute(select(ToolApproval))).scalars().all()
        assert len(ap_rows) == 1
        assert ap_rows[0].tool_call_id is not None
        assert ap_rows[0].tool_call_id == result.record_id

    async def test_caller_receives_valid_result_despite_start_failure(
        self, db_session, patched_async_sessions
    ):
        """dispatch_tool_call returns needs_approval=True with valid record_id
        and approval_id even though _start_tool_call's background task fails.
        loop.py's approval-wait path proceeds unaware of the orphan.
        """
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_approval_decision("exec tier", timeout=120)), \
             patch("app.agent.tool_dispatch._start_tool_call",
                   new_callable=AsyncMock,
                   side_effect=RuntimeError("DB down")):
            result = await dispatch_tool_call(
                name="exec_cmd", allowed_tool_names=None, **_kw()
            )

        assert result.needs_approval is True
        assert result.record_id is not None
        assert result.approval_id is not None
        assert result.approval_timeout == 120


# ---------------------------------------------------------------------------
# Capability-gate path (tool_dispatch.py:446-473)
# ---------------------------------------------------------------------------

class TestCapabilityGateHappyPath:
    async def test_when_start_completes_then_both_rows_exist_and_linked(
        self, db_session, patched_async_sessions, monkeypatch
    ):
        """Capability-gate path has identical ordering to the policy-gate path.
        After flush both rows exist and ToolApproval.tool_call_id == ToolCall.id.
        """
        from app.config import settings
        monkeypatch.setattr(settings, "CAPABILITY_APPROVAL", "required")

        with patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.capability_session.is_approved", return_value=False), \
             patch("app.agent.bots.get_bot",
                   return_value=MagicMock(carapaces=[])), \
             patch("app.agent.carapaces.get_carapace",
                   return_value={"name": "My Cap", "description": "", "local_tools": []}):
            await dispatch_tool_call(
                name="activate_capability",
                allowed_tool_names=None,
                **_kw(args='{"id": "my-cap"}'),
            )

        await _flush()
        db_session.expire_all()

        tc_rows = (await db_session.execute(select(ToolCall))).scalars().all()
        ap_rows = (await db_session.execute(select(ToolApproval))).scalars().all()
        assert len(tc_rows) == 1
        assert len(ap_rows) == 1
        assert tc_rows[0].status == "awaiting_approval"
        assert ap_rows[0].tool_call_id == tc_rows[0].id


class TestCapabilityGateOrphanPointer:
    async def test_when_start_tool_call_raises_then_approval_commits_with_ghost_id(
        self, db_session, patched_async_sessions, monkeypatch
    ):
        """Capability-gate path has the same drift risk as the policy-gate path.
        _start_tool_call failure → ToolApproval commits with ghost tool_call_id.
        """
        from app.config import settings
        monkeypatch.setattr(settings, "CAPABILITY_APPROVAL", "required")

        with patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock, return_value=None), \
             patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.capability_session.is_approved", return_value=False), \
             patch("app.agent.bots.get_bot",
                   return_value=MagicMock(carapaces=[])), \
             patch("app.agent.carapaces.get_carapace",
                   return_value={"name": "My Cap", "description": "", "local_tools": []}), \
             patch("app.agent.tool_dispatch._start_tool_call",
                   new_callable=AsyncMock,
                   side_effect=RuntimeError("session pool exhausted")):
            result = await dispatch_tool_call(
                name="activate_capability",
                allowed_tool_names=None,
                **_kw(args='{"id": "my-cap"}'),
            )

        await _flush()
        db_session.expire_all()

        tc_rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(tc_rows) == 0

        ap_rows = (await db_session.execute(select(ToolApproval))).scalars().all()
        assert len(ap_rows) == 1
        assert ap_rows[0].tool_call_id is not None
        assert ap_rows[0].tool_call_id == result.record_id
