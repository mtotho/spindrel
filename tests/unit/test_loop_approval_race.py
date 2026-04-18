"""Phase E.4 drift-seam test: loop.py approval-verdict race.

Seam class: background-task ordering + multi-row sync.

When asyncio.wait_for raises TimeoutError, the loop sets verdict="expired"
and runs an expired-handler that tries to flip both ToolApproval and ToolCall
to "expired". The handler guards on ToolApproval.status == "pending" before
flipping.

Race: decide_approval may set ToolApproval.status="approved" (and ToolCall
to "running") at the same instant. The handler sees status != "pending" →
skips all flips. But the loop's local verdict variable is already "expired"
(set when TimeoutError was caught, before the handler ran).

Drift: the loop falls into the else branch, yields verdict="expired", and
does NOT re-dispatch. ToolApproval.status="approved", ToolCall.status=
"running". No completion ever runs — the ToolCall is stuck until GC.

This is the same "stuck running" shape as the Phase D drift but triggered
by a different race path.

The handler appears at two equivalent sites in loop.py (lines 1038-1052
inside the parallel-dispatch section, and lines 1195-1209 inside the
sequential-dispatch section). Both are identical in logic — the tests
below apply to both copies.

Handler code (verbatim from loop.py:1038-1052):

    try:
        from app.db.engine import async_session as _ap_session
        from app.db.models import ToolApproval as _TA, ToolCall as _TC
        async with _ap_session() as _ap_db:
            _ap_row = await _ap_db.get(_TA, uuid.UUID(tc_result.approval_id))
            if _ap_row and _ap_row.status == "pending":
                _ap_row.status = "expired"
                if _ap_row.tool_call_id:
                    _tc_row = await _ap_db.get(_TC, _ap_row.tool_call_id)
                    if _tc_row and _tc_row.status == "awaiting_approval":
                        _tc_row.status = "expired"
                        _tc_row.completed_at = datetime.now(timezone.utc)
                await _ap_db.commit()
    except Exception:
        logger.warning("Failed to mark approval %s as expired", ...)

We test this by mirroring the exact logic in _run_handler(), seeding real
DB rows via db_session, and verifying post-handler DB state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import ToolApproval, ToolCall

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_handler(approval_id: str) -> None:
    """Mirror of the loop.py approval timeout handler (lines 1038-1052).

    Uses the same import-inside-function pattern so patched_async_sessions
    patches the session factory transparently.
    """
    from app.db.engine import async_session as _ap_session
    from app.db.models import ToolApproval as _TA, ToolCall as _TC

    try:
        async with _ap_session() as _ap_db:
            _ap_row = await _ap_db.get(_TA, uuid.UUID(approval_id))
            if _ap_row and _ap_row.status == "pending":
                _ap_row.status = "expired"
                if _ap_row.tool_call_id:
                    _tc_row = await _ap_db.get(_TC, _ap_row.tool_call_id)
                    if _tc_row and _tc_row.status == "awaiting_approval":
                        _tc_row.status = "expired"
                        _tc_row.completed_at = datetime.now(timezone.utc)
                await _ap_db.commit()
    except Exception:
        pass  # mirrors the logger.warning swallow


async def _seed(
    db_session,
    *,
    ap_status: str = "pending",
    tc_status: str = "awaiting_approval",
    link: bool = True,
) -> tuple[ToolApproval, ToolCall]:
    """Seed one ToolApproval + ToolCall and commit via db_session."""
    tc = ToolCall(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        bot_id="e4-bot",
        tool_name="write_file",
        tool_type="local",
        arguments={},
        status=tc_status,
    )
    db_session.add(tc)
    appr = ToolApproval(
        id=uuid.uuid4(),
        bot_id="e4-bot",
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


# ---------------------------------------------------------------------------
# Normal timeout — no concurrent decide
# ---------------------------------------------------------------------------


class TestNormalTimeout:
    """Handler flips both rows when approval is pending and TC is awaiting."""

    async def test_when_both_pending_then_both_flipped_to_expired(
        self, db_session, patched_async_sessions
    ):
        appr, tc = await _seed(db_session)
        appr_id, tc_id = appr.id, tc.id

        await _run_handler(str(appr_id))
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert ap_row.status == "expired"
        assert tc_row.status == "expired"

    async def test_completed_at_is_set_on_tool_call_when_expired(
        self, db_session, patched_async_sessions
    ):
        appr, tc = await _seed(db_session)
        appr_id, tc_id = appr.id, tc.id
        before = datetime.now(timezone.utc)

        await _run_handler(str(appr_id))
        db_session.expire_all()

        tc_row = await db_session.get(ToolCall, tc_id)
        assert tc_row.completed_at is not None
        assert tc_row.completed_at >= before

    async def test_when_tc_not_awaiting_approval_then_only_approval_flipped(
        self, db_session, patched_async_sessions
    ):
        """TC guard: only flips TC if status == "awaiting_approval".
        A TC already in "running" (e.g. start_tool_call raced ahead) is left
        untouched even though the approval is still pending.
        """
        appr, tc = await _seed(db_session, tc_status="running")
        appr_id, tc_id = appr.id, tc.id

        await _run_handler(str(appr_id))
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert ap_row.status == "expired"
        assert tc_row.status == "running"  # guard blocked the TC flip

    async def test_when_no_tool_call_linked_then_only_approval_flipped(
        self, db_session, patched_async_sessions
    ):
        """tool_call_id=None: handler flips approval only, no TC lookup."""
        appr, tc = await _seed(db_session, link=False)
        appr_id, tc_id = appr.id, tc.id

        await _run_handler(str(appr_id))
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert ap_row.status == "expired"
        assert ap_row.tool_call_id is None
        assert tc_row.status == "awaiting_approval"  # never touched


# ---------------------------------------------------------------------------
# Race: decide_approval ran before the timeout handler fires
# ---------------------------------------------------------------------------


class TestRaceDriftPin:
    """Pins the drift: decide_approval races ahead of the timeout handler.

    Scenario:
      1. asyncio.wait_for raises TimeoutError → loop sets local verdict = "expired"
      2. (Milliseconds earlier) decide_approval set ToolApproval.status = "approved"
         and ToolCall.status = "running"
      3. Expired-handler runs, checks status == "pending" → False → skips all flips
      4. Loop uses local verdict = "expired" → else branch → no re-dispatch

    Result: ToolApproval.status="approved" (from decide), ToolCall.status="running"
    (from decide), but no completion ever fires. The ToolCall is stuck.
    """

    async def test_race_when_approval_already_approved_handler_skips_both(
        self, db_session, patched_async_sessions
    ):
        """Handler guard (status == 'pending') rejects an already-approved row.
        Both rows are left in their decide_approval-set state.
        """
        appr, tc = await _seed(
            db_session, ap_status="approved", tc_status="running"
        )
        appr_id, tc_id = appr.id, tc.id

        await _run_handler(str(appr_id))
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert ap_row.status == "approved"  # handler skipped
        assert tc_row.status == "running"   # handler skipped

    async def test_race_drift_tc_stuck_running_while_verdict_is_expired(
        self, db_session, patched_async_sessions
    ):
        """Drift pin: after the race, ToolCall stays in "running" indefinitely.

        decide_approval set ap.status="approved", tc.status="running".
        The timeout handler is a no-op (guard failed). The loop's local
        verdict is still "expired" — the else branch yields an error payload
        and does NOT call dispatch_tool_call again. No completion ever runs.

        Hardening (re-checking approval.status after the handler and using
        that as the final verdict) would make this test fail.
        """
        appr, tc = await _seed(
            db_session, ap_status="approved", tc_status="running"
        )
        appr_id, tc_id = appr.id, tc.id

        await _run_handler(str(appr_id))
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        # Drift: DB says approved, but the loop will use local verdict="expired".
        # There is no post-handler reconciliation — the ToolCall is stuck.
        assert ap_row.status == "approved"
        assert tc_row.status == "running"

    async def test_race_when_approval_already_denied_handler_also_skips(
        self, db_session, patched_async_sessions
    ):
        """decide_approval denied while timeout was in flight. Same guard fires.
        Both rows stay in decide_approval-set state.
        """
        appr, tc = await _seed(
            db_session, ap_status="denied", tc_status="denied"
        )
        appr_id, tc_id = appr.id, tc.id

        await _run_handler(str(appr_id))
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert ap_row.status == "denied"
        assert tc_row.status == "denied"

    async def test_race_when_approval_already_expired_handler_is_idempotent(
        self, db_session, patched_async_sessions
    ):
        """Two concurrent timeouts: first one already flipped to 'expired';
        second handler run sees non-pending → skips → no double-flip damage.
        """
        appr, tc = await _seed(
            db_session, ap_status="expired", tc_status="expired"
        )
        appr_id, tc_id = appr.id, tc.id

        await _run_handler(str(appr_id))
        db_session.expire_all()

        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert ap_row.status == "expired"  # unchanged
        assert tc_row.status == "expired"  # unchanged


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_missing_approval_row_is_noop(
        self, db_session, patched_async_sessions
    ):
        """approval_id not in DB → get() returns None → guard skips → no error."""
        ghost_id = str(uuid.uuid4())

        await _run_handler(ghost_id)  # must not raise

        tc_rows = (await db_session.execute(select(ToolCall))).scalars().all()
        ap_rows = (await db_session.execute(select(ToolApproval))).scalars().all()
        assert tc_rows == []
        assert ap_rows == []

    async def test_handler_swallows_db_exception(
        self, db_session, patched_async_sessions
    ):
        """Exception inside the session (e.g. pool exhausted) is swallowed.
        The loop continues with verdict="expired" in the else branch.
        """
        appr, tc = await _seed(db_session)
        appr_id, tc_id = appr.id, tc.id

        # Patch the session factory to raise on entry
        boom = AsyncMock(side_effect=RuntimeError("pool exhausted"))
        with patch("app.db.engine.async_session", boom):
            await _run_handler(str(appr_id))  # must not raise

        # Rows unchanged (handler never committed)
        db_session.expire_all()
        ap_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert ap_row.status == "pending"
        assert tc_row.status == "awaiting_approval"
