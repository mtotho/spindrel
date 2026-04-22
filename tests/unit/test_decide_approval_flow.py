"""Tests for POST /api/v1/approvals/{id}/decide (`decide_approval`).

The decide endpoint is the pivot that turns a pending tool approval into one
of three terminal outcomes — approved, denied, or stale. Along the way it:

1. Flips ``ToolApproval.status``.
2. Flips the linked ``ToolCall.status`` (guarded on current status).
3. Optionally creates a ``ToolPolicyRule`` (bot- or global-scoped).
4. Adds a session-scoped allow + resolves the waiting future.

This file covers each of those paths with real DB writes so the post-decide
DB state matches what the snapshot endpoint and subsequent re-dispatch rely
on. Because the five side-effects share one transaction, a regression in any
one of them corrupts the rest — the asserts below pin the contract across
all five.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.agent import approval_pending, session_allows
from app.db.models import ToolApproval, ToolCall, ToolPolicyRule
from app.routers.api_v1_approvals import DecideRequest, decide_approval


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Isolation: the approval router mutates three module-level singletons
# (approval_pending._pending, session_allows._allows, tool_policies cache).
# Without per-test resets earlier tests leak state into later ones (B.28).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_module_state():
    approval_pending._pending.clear()
    session_allows._allows.clear()
    from app.services import tool_policies
    tool_policies.invalidate_cache()
    yield
    approval_pending._pending.clear()
    session_allows._allows.clear()
    tool_policies.invalidate_cache()


async def _seed_pending_approval(
    db_session,
    *,
    bot_id: str = "test-bot",
    with_tool_call: bool = True,
    tc_status: str = "awaiting_approval",
    correlation_id: uuid.UUID | None = None,
) -> tuple[ToolApproval, ToolCall | None]:
    """Insert a pending ToolApproval (and its linked ToolCall) ready to decide."""
    corr = correlation_id or uuid.uuid4()
    tc: ToolCall | None = None
    if with_tool_call:
        tc = ToolCall(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            bot_id=bot_id,
            tool_name="write_file",
            tool_type="local",
            arguments={"path": "/tmp/x"},
            correlation_id=corr,
            status=tc_status,
        )
        db_session.add(tc)
    appr = ToolApproval(
        id=uuid.uuid4(),
        bot_id=bot_id,
        correlation_id=corr,
        tool_name="write_file",
        tool_type="local",
        arguments={"path": "/tmp/x"},
        reason="policy gate",
        status="pending",
        tool_call_id=tc.id if tc else None,
        timeout_seconds=300,
    )
    db_session.add(appr)
    await db_session.commit()
    return appr, tc


class TestApproveFlow:
    async def test_approve_flips_approval_and_tool_call_status(self, db_session):
        appr, tc = await _seed_pending_approval(db_session)

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=True, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        await db_session.refresh(tc)
        assert out.status == "approved"
        assert tc.status == "running"
        assert tc.completed_at is None

    async def test_approve_adds_session_allow_for_redispatch(self, db_session):
        """Session allow is how the re-dispatch path skips re-running the policy gate."""
        appr, _ = await _seed_pending_approval(db_session)

        await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=True, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        assert session_allows.is_session_allowed(str(appr.correlation_id), appr.tool_name)

    async def test_approve_with_bot_rule_creates_scoped_rule(self, db_session):
        appr, _ = await _seed_pending_approval(db_session, bot_id="rolland")

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(
                approved=True, decided_by="api:admin",
                create_rule={
                    "tool_name": "write_file",
                    "conditions": {"path_prefix": "/tmp/"},
                    "scope": "bot",
                    "priority": 50,
                },
            ),
            _auth=None, db=db_session,
        )

        rule = (await db_session.execute(
            select(ToolPolicyRule).where(ToolPolicyRule.id == out.rule_created)
        )).scalar_one()
        assert rule.bot_id == "rolland"
        assert rule.action == "allow"
        assert rule.conditions == {"path_prefix": "/tmp/"}

    async def test_approve_with_global_rule_nulls_bot_id(self, db_session):
        """scope='global' must set bot_id=None so the rule applies to every bot."""
        appr, _ = await _seed_pending_approval(db_session, bot_id="rolland")

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(
                approved=True, decided_by="api:admin",
                create_rule={"tool_name": "write_file", "scope": "global"},
            ),
            _auth=None, db=db_session,
        )

        rule = (await db_session.execute(
            select(ToolPolicyRule).where(ToolPolicyRule.id == out.rule_created)
        )).scalar_one()
        assert rule.bot_id is None

    async def test_deny_with_create_rule_does_not_create_rule(self, db_session):
        """create_rule only fires on approve — a denied approval should leave no rule."""
        appr, _ = await _seed_pending_approval(db_session)

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(
                approved=False, decided_by="api:admin",
                create_rule={"tool_name": "write_file", "scope": "bot"},
            ),
            _auth=None, db=db_session,
        )

        assert out.rule_created is None
        rules = (await db_session.execute(select(ToolPolicyRule))).scalars().all()
        assert rules == []


class TestDenyFlow:
    async def test_deny_flips_tool_call_to_denied_with_completed_at(self, db_session):
        appr, tc = await _seed_pending_approval(db_session)

        await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=False, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        await db_session.refresh(tc)
        assert tc.status == "denied"
        assert tc.completed_at is not None

    async def test_deny_does_not_add_session_allow(self, db_session):
        appr, _ = await _seed_pending_approval(db_session)

        await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=False, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        assert not session_allows.is_session_allowed(str(appr.correlation_id), appr.tool_name)


class TestGuardBranches:
    async def test_missing_approval_returns_404(self, db_session):
        with pytest.raises(HTTPException) as exc:
            await decide_approval(
                approval_id=uuid.uuid4(),
                body=DecideRequest(approved=True, decided_by="api:admin"),
                _auth=None, db=db_session,
            )
        assert exc.value.status_code == 404

    async def test_already_decided_approval_returns_409(self, db_session):
        appr, _ = await _seed_pending_approval(db_session)
        appr.status = "approved"
        appr.decided_at = datetime.now(timezone.utc)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await decide_approval(
                approval_id=appr.id,
                body=DecideRequest(approved=True, decided_by="api:admin"),
                _auth=None, db=db_session,
            )
        assert exc.value.status_code == 409

    async def test_approval_without_tool_call_id_decides_cleanly(self, db_session):
        """Pre-migration rows have tool_call_id=None — decide must still succeed."""
        appr, _ = await _seed_pending_approval(db_session, with_tool_call=False)

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=True, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        assert out.status == "approved"


class TestToolCallStatusGuard:
    async def test_tool_call_already_running_leaves_status_untouched_on_deny(self, db_session):
        """Silent-drift case: deny while the row is no longer awaiting_approval.

        Pins current behavior: ToolApproval flips to 'denied' but ToolCall stays
        'running'. This leaves a denied approval pointing at a running tool call —
        the snapshot endpoint will keep showing the call as in-flight until the
        10-minute window expires. Documents a real DB inconsistency; the guard
        clause at ``api_v1_approvals.py:181`` is the single source of truth.
        """
        appr, tc = await _seed_pending_approval(
            db_session, tc_status="running",  # already re-dispatched somehow
        )

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=False, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        await db_session.refresh(tc)
        assert out.status == "denied"
        assert tc.status == "running"  # drift — intentional or bug, pinned here
        assert tc.completed_at is None

    async def test_tool_call_orphan_pointer_decides_without_error(self, db_session):
        """tool_call_id points at a deleted row — endpoint must not crash."""
        appr, tc = await _seed_pending_approval(db_session)
        await db_session.delete(tc)
        await db_session.commit()

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=True, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        assert out.status == "approved"


class TestFutureResolution:
    async def test_approve_resolves_waiting_future(self, db_session):
        appr, _ = await _seed_pending_approval(db_session)
        fut = approval_pending.create_approval_pending(str(appr.id))

        await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=True, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        assert fut.done()
        assert fut.result() == "approved"

    async def test_deny_resolves_future_with_denied_verdict(self, db_session):
        appr, _ = await _seed_pending_approval(db_session)
        fut = approval_pending.create_approval_pending(str(appr.id))

        await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=False, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        assert fut.result() == "denied"

    async def test_decide_without_waiting_future_succeeds_silently(self, db_session):
        """Expired-then-decided case: loop gave up waiting, decide still persists."""
        appr, _ = await _seed_pending_approval(db_session)

        out = await decide_approval(
            approval_id=appr.id,
            body=DecideRequest(approved=True, decided_by="api:admin"),
            _auth=None, db=db_session,
        )

        assert out.status == "approved"
        assert approval_pending.pending_count() == 0
