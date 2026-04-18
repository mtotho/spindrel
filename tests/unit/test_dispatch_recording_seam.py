"""Phase C seam tests: dispatch_tool_call → recording → real DB.

Phase B.4 (test_tool_dispatch_core_gaps.py) pinned policy/approval logic in
isolation with all recording mocked. test_tool_call_status_lifecycle.py tested
_start_tool_call/_complete_tool_call in isolation. This file fills the seam:

    dispatch_tool_call
      → _start_tool_call  (safe_create_task — fire-and-forget, status='running')
      → call_local_tool   (awaited inline)
      → _complete_tool_call (safe_create_task — fire-and-forget, terminal status)
      → ToolCall row in test DB

Each test asserts on the real SQLite ToolCall row rather than mocked calls,
exercising the full status-lifecycle contract (running → done / error / denied /
awaiting_approval). Also verifies the ToolApproval.tool_call_id back-reference
is correctly wired on the approval path.
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
    """Minimal kwargs for dispatch_tool_call. channel_id=None suppresses
    _notify_approval_request fire-and-forget in the approval path."""
    base = dict(
        args="{}",
        tool_call_id="tc_1",
        bot_id="seam-test-bot",
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


def _deny_decision(reason: str = "blocked") -> MagicMock:
    d = MagicMock()
    d.action = "deny"
    d.reason = reason
    return d


def _approval_decision(reason: str = "needs review", timeout: int = 300) -> MagicMock:
    d = MagicMock()
    d.action = "require_approval"
    d.reason = reason
    d.rule_id = None
    d.tier = None
    d.timeout = timeout
    return d


async def _flush(n: int = 5) -> None:
    """Yield to the event loop n times so fire-and-forget tasks complete.

    _start_tool_call and _complete_tool_call each open an aiosqlite session
    (several yields each). Five ticks is enough for both to land.
    """
    for _ in range(n):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Normal dispatch (running → done / error)
# ---------------------------------------------------------------------------

class TestNormalDispatchRecordingSeam:
    async def test_when_tool_succeeds_then_toolcall_status_is_done(
        self, db_session, patched_async_sessions
    ):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool",
                   new_callable=AsyncMock, return_value='{"text": "hello"}'):
            await dispatch_tool_call(name="echo", allowed_tool_names=None, **_kw())

        await _flush()
        db_session.expire_all()

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.tool_name == "echo"
        assert row.status == "done"
        assert row.completed_at is not None
        assert row.result is not None

    async def test_when_tool_reports_error_json_then_status_is_error(
        self, db_session, patched_async_sessions
    ):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool",
                   new_callable=AsyncMock, return_value='{"error": "file not found"}'):
            await dispatch_tool_call(name="read_file", allowed_tool_names=None, **_kw())

        await _flush()
        db_session.expire_all()

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "error"
        assert row.error == "file not found"
        assert row.completed_at is not None

    async def test_start_and_complete_share_same_row_id(
        self, db_session, patched_async_sessions
    ):
        """_start_tool_call inserts the row; _complete_tool_call UPDATEs it.
        Exactly one ToolCall row must exist — not two."""
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool",
                   new_callable=AsyncMock, return_value='{"ok": 1}'):
            await dispatch_tool_call(name="list_files", allowed_tool_names=None, **_kw())

        await _flush()
        db_session.expire_all()

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(rows) == 1

    async def test_iteration_and_bot_id_stored_on_row(
        self, db_session, patched_async_sessions
    ):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch.call_local_tool",
                   new_callable=AsyncMock, return_value='{}'):
            await dispatch_tool_call(
                name="search", allowed_tool_names=None,
                **_kw(iteration=3),
            )

        await _flush()
        db_session.expire_all()

        row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert row.bot_id == "seam-test-bot"
        assert row.iteration == 3
        assert row.tool_type == "local"


# ---------------------------------------------------------------------------
# Denied paths (auth deny + policy deny)
# ---------------------------------------------------------------------------

class TestDeniedDispatchRecordingSeam:
    async def test_when_auth_denied_then_denied_row_created(
        self, db_session, patched_async_sessions
    ):
        """Auth check fires before policy — _record_tool_call one-shot insert."""
        await dispatch_tool_call(
            name="forbidden_tool",
            allowed_tool_names={"other_tool"},
            **_kw(),
        )
        await _flush()
        db_session.expire_all()

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.tool_name == "forbidden_tool"
        assert row.status == "denied"
        assert row.completed_at is not None

    async def test_when_policy_denies_then_denied_row_created(
        self, db_session, patched_async_sessions
    ):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_deny_decision("security policy")), \
             patch("app.agent.tool_dispatch.call_local_tool",
                   new_callable=AsyncMock) as mock_call:
            await dispatch_tool_call(name="risky_tool", allowed_tool_names=None, **_kw())

        await _flush()
        db_session.expire_all()

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "denied"
        mock_call.assert_not_called()


# ---------------------------------------------------------------------------
# Approval path (awaiting_approval + ToolApproval linkage)
# ---------------------------------------------------------------------------

class TestApprovalDispatchRecordingSeam:
    async def test_when_approval_required_then_awaiting_approval_row_created(
        self, db_session, patched_async_sessions
    ):
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_approval_decision("needs human review")):
            result = await dispatch_tool_call(
                name="write_file", allowed_tool_names=None, **_kw()
            )

        await _flush()
        db_session.expire_all()

        assert result.needs_approval is True
        tc_rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(tc_rows) == 1
        assert tc_rows[0].status == "awaiting_approval"
        assert tc_rows[0].tool_name == "write_file"
        assert tc_rows[0].completed_at is None

    async def test_when_approval_required_then_record_id_matches_toolcall_row(
        self, db_session, patched_async_sessions
    ):
        """result.record_id must point to the ToolCall row so re-dispatch
        (loop.py) can call dispatch_tool_call(existing_record_id=...) to
        UPDATE the same row on completion rather than inserting a new one."""
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_approval_decision()):
            result = await dispatch_tool_call(
                name="delete_file", allowed_tool_names=None, **_kw()
            )

        await _flush()
        db_session.expire_all()

        tc_row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert result.record_id == tc_row.id

    async def test_when_approval_required_then_tool_approval_links_to_toolcall(
        self, db_session, patched_async_sessions
    ):
        """ToolApproval.tool_call_id ← ToolCall.id.

        The decide endpoint reads this linkage to flip the ToolCall status on
        approve/deny (tested in test_tool_call_status_lifecycle.py). This test
        pins that dispatch_tool_call wires the IDs correctly at creation time.
        """
        with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
             patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
             patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False), \
             patch("app.agent.tool_dispatch._check_tool_policy",
                   new_callable=AsyncMock,
                   return_value=_approval_decision("exec tier")):
            await dispatch_tool_call(
                name="exec_command", allowed_tool_names=None, **_kw()
            )

        await _flush()
        db_session.expire_all()

        tc_rows = (await db_session.execute(select(ToolCall))).scalars().all()
        approval_rows = (await db_session.execute(select(ToolApproval))).scalars().all()
        assert len(tc_rows) == 1
        assert len(approval_rows) == 1
        assert approval_rows[0].tool_call_id == tc_rows[0].id
        assert approval_rows[0].status == "pending"
