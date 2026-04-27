"""Tests for approval-timeout reconciliation in ``app.agent.loop``."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agent import approval_pending
from app.agent.loop import resolve_approval_verdict
from app.db.models import ToolApproval, ToolCall

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_pending_state():
    approval_pending._pending.clear()
    yield
    approval_pending._pending.clear()


async def _seed(
    db_session,
    *,
    ap_status: str = "pending",
    tc_status: str = "awaiting_approval",
    link: bool = True,
) -> tuple[ToolApproval, ToolCall]:
    tc = ToolCall(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        bot_id="approval-race-bot",
        tool_name="write_file",
        tool_type="local",
        arguments={},
        status=tc_status,
    )
    db_session.add(tc)
    appr = ToolApproval(
        id=uuid.uuid4(),
        bot_id="approval-race-bot",
        tool_name="write_file",
        tool_type="local",
        arguments={},
        reason="policy gate",
        status=ap_status,
        tool_call_id=tc.id if link else None,
        timeout_seconds=300,
    )
    db_session.add(appr)
    await db_session.commit()
    return appr, tc


class TestResolvedApprovals:
    async def test_returns_approved_when_future_is_resolved(self, db_session):
        appr, _ = await _seed(db_session)

        task = asyncio.create_task(
            resolve_approval_verdict(str(appr.id), timeout_seconds=1)
        )
        await asyncio.sleep(0)
        assert approval_pending.resolve_approval(str(appr.id), "approved") is True

        verdict = await task
        assert verdict == "approved"
        assert approval_pending.pending_count() == 0

    async def test_returns_denied_when_future_is_resolved(self, db_session):
        appr, _ = await _seed(db_session)

        task = asyncio.create_task(
            resolve_approval_verdict(str(appr.id), timeout_seconds=1)
        )
        await asyncio.sleep(0)
        assert approval_pending.resolve_approval(str(appr.id), "denied") is True

        verdict = await task
        assert verdict == "denied"
        assert approval_pending.pending_count() == 0


class TestTimeoutReconciliation:
    async def test_timeout_marks_pending_rows_expired(
        self, db_session, patched_async_sessions
    ):
        appr, tc = await _seed(db_session)
        appr_id, tc_id = appr.id, tc.id

        verdict = await resolve_approval_verdict(str(appr_id), timeout_seconds=0.01)
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert verdict == "expired"
        assert ap_row.status == "expired"
        assert tc_row.status == "expired"
        assert tc_row.completed_at is not None
        assert approval_pending.pending_count() == 0

    async def test_timeout_returns_db_truth_when_already_approved(
        self, db_session, patched_async_sessions
    ):
        appr, tc = await _seed(
            db_session, ap_status="approved", tc_status="running"
        )
        appr_id, tc_id = appr.id, tc.id

        verdict = await resolve_approval_verdict(str(appr_id), timeout_seconds=0.01)
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert verdict == "approved"
        assert ap_row.status == "approved"
        assert tc_row.status == "running"
        assert approval_pending.pending_count() == 0

    async def test_timeout_returns_db_truth_when_already_denied(
        self, db_session, patched_async_sessions
    ):
        appr, tc = await _seed(
            db_session, ap_status="denied", tc_status="denied"
        )
        appr_id, tc_id = appr.id, tc.id

        verdict = await resolve_approval_verdict(str(appr_id), timeout_seconds=0.01)
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert verdict == "denied"
        assert ap_row.status == "denied"
        assert tc_row.status == "denied"
        assert approval_pending.pending_count() == 0

    async def test_timeout_with_missing_row_returns_expired(
        self, patched_async_sessions
    ):
        verdict = await resolve_approval_verdict(str(uuid.uuid4()), timeout_seconds=0.01)

        assert verdict == "expired"
        assert approval_pending.pending_count() == 0
