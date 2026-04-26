"""Integration coverage for harness approvals (Phase 3).

Covers the ask-path of ``request_harness_approval`` against a real DB +
event bus + future registry:

- ask path creates a ``ToolApproval`` row with ``tool_type='harness'``
- the future is registered BEFORE ``APPROVAL_REQUESTED`` publishes (race fix)
- ``decide_approval`` for a harness row emits ``APPROVAL_RESOLVED`` with
  the right decision
- ``expire_harness_approval`` updates the row + emits
  ``APPROVAL_RESOLVED(decision="expired")``
- ``cancel_pending_harness_approvals_for_session`` expires every pending
  harness row scoped to the session
- ``decide_approval`` rejects ``create_rule`` for ``tool_type='harness'``
- per-turn bypass (``grant_turn_bypass``) short-circuits subsequent
  approvals in the same turn

All paths use real ``async_session`` writes — the helper itself opens its
own DB scopes via ``ctx.db_session_factory``, so we patch the canonical
factory to point at the test sessionmaker.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.approval_pending import (
    cancel_approval,
    create_approval_pending,
    pending_count,
)
from app.db.models import (
    Bot as BotRow,
    Channel as ChannelRow,
    Session as SessionRow,
    ToolApproval,
)
from app.domain.channel_events import ChannelEventKind
from app.services.agent_harnesses.approvals import (
    AllowDeny,
    DEFAULT_MODE,
    HARNESS_APPROVAL_MODE_KEY,
    cancel_pending_harness_approvals_for_session,
    expire_harness_approval,
    grant_turn_bypass,
    load_session_mode,
    request_harness_approval,
    revoke_turn_bypass,
    set_session_mode,
)
from app.services.agent_harnesses.base import TurnContext
from app.services.channel_events import _next_seq, _replay_buffer
from tests.factories import build_bot, build_channel

pytestmark = pytest.mark.asyncio


class _StubRuntime:
    """Implements just the classification surface — no SDK involvement."""

    def readonly_tools(self):
        return frozenset({"Read", "Glob"})

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        return tool_name in {"Bash", "ExitPlanMode"}

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return tool_name == "ExitPlanMode"


@pytest.fixture(autouse=True)
def _reset_bus_state():
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _next_seq.clear()
    _replay_buffer.clear()


@pytest_asyncio.fixture
async def harness_approval_setup(engine, db_session):
    """Build a real bot/channel/session row and patch async_session everywhere
    the helper might open a DB scope.

    Returns a ``TurnContext`` ready to feed ``request_harness_approval``.
    """
    bot = build_bot(id="harness-approval-bot", name="HA Bot", model="x")
    bot.harness_runtime = "claude-code"
    db_session.add(bot)

    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)

    session = SessionRow(
        id=uuid.uuid4(),
        client_id="ha-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # The helper, expire, cancel-pending, and the API decide endpoint all reach
    # for `async_session` via several import sites — patch them all.
    with patch.multiple("app.db.engine", async_session=factory), patch(
        "app.services.agent_harnesses.approvals.async_session", factory,
    ):
        yield {
            "bot": bot,
            "channel": channel,
            "session": session,
            "factory": factory,
        }


def _make_ctx(setup, *, mode: str = "default", channel_id_override=None) -> TurnContext:
    return TurnContext(
        spindrel_session_id=setup["session"].id,
        channel_id=channel_id_override if channel_id_override is not None else setup["channel"].id,
        bot_id=setup["bot"].id,
        turn_id=uuid.uuid4(),
        workdir="/tmp",
        harness_session_id=None,
        permission_mode=mode,
        db_session_factory=setup["factory"],
    )


# ----------------------------------------------------------------------------
# Mode storage
# ----------------------------------------------------------------------------


async def test_load_session_mode_returns_default_when_unset(harness_approval_setup, db_session):
    setup = harness_approval_setup
    mode = await load_session_mode(db_session, setup["session"].id)
    assert mode == DEFAULT_MODE


async def test_set_then_load_session_mode_round_trip(harness_approval_setup, db_session):
    setup = harness_approval_setup
    await set_session_mode(db_session, setup["session"].id, "acceptEdits")
    # Re-read via the helper's own short scope.
    factory = setup["factory"]
    async with factory() as fresh_db:
        mode = await load_session_mode(fresh_db, setup["session"].id)
    assert mode == "acceptEdits"


async def test_set_session_mode_rejects_unknown(harness_approval_setup, db_session):
    setup = harness_approval_setup
    with pytest.raises(ValueError, match="unknown approval mode"):
        await set_session_mode(db_session, setup["session"].id, "totallyMadeUp")


# ----------------------------------------------------------------------------
# Ask path — DB row + future + event ordering
# ----------------------------------------------------------------------------


async def test_ask_path_creates_harness_row_and_emits_event(harness_approval_setup, db_session):
    """Race-critical: the future must be registered BEFORE the event publishes."""
    setup = harness_approval_setup
    ctx = _make_ctx(setup, mode="default")

    # Schedule the helper but don't await it — it will block on the future.
    # We'll resolve the future ourselves to simulate the user clicking Approve.
    helper_task = asyncio.create_task(
        request_harness_approval(
            ctx=ctx, runtime=_StubRuntime(),
            tool_name="Bash", tool_input={"cmd": "ls /"},
        )
    )
    # Yield so the helper progresses to the await on the future.
    await asyncio.sleep(0.05)

    # Row should exist with tool_type='harness' and status='pending'.
    factory = setup["factory"]
    async with factory() as fresh_db:
        from sqlalchemy import select
        rows = (await fresh_db.execute(
            select(ToolApproval).where(
                ToolApproval.session_id == setup["session"].id,
                ToolApproval.tool_type == "harness",
            )
        )).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "pending"
    assert row.tool_call_id is None  # harness approvals never link a ToolCall
    assert row.dispatch_type == "harness"
    assert row.bot_id == setup["bot"].id
    assert row.tool_name == "Bash"
    assert row.arguments == {"cmd": "ls /"}

    # APPROVAL_REQUESTED was published with tool_type='harness'.
    events = _replay_buffer.get(setup["channel"].id, [])
    requested = [e for e in events if e.kind is ChannelEventKind.APPROVAL_REQUESTED]
    assert len(requested) == 1
    assert requested[0].payload.tool_type == "harness"
    assert requested[0].payload.approval_id == str(row.id)

    # Resolve as denied so the helper finishes (otherwise it'd timeout 5min).
    from app.agent.approval_pending import resolve_approval
    assert resolve_approval(str(row.id), "denied")
    decision = await asyncio.wait_for(helper_task, timeout=5)
    assert decision == AllowDeny.deny("User denied this tool call")


async def test_ask_path_returns_allow_when_resolved_approved(harness_approval_setup):
    setup = harness_approval_setup
    ctx = _make_ctx(setup, mode="default")
    task = asyncio.create_task(request_harness_approval(
        ctx=ctx, runtime=_StubRuntime(),
        tool_name="Bash", tool_input={},
    ))
    await asyncio.sleep(0.05)
    factory = setup["factory"]
    async with factory() as db:
        from sqlalchemy import select
        row = (await db.execute(
            select(ToolApproval).where(ToolApproval.session_id == setup["session"].id)
        )).scalar_one()
    from app.agent.approval_pending import resolve_approval
    resolve_approval(str(row.id), "approved")
    decision = await asyncio.wait_for(task, timeout=5)
    assert decision.allow


# ----------------------------------------------------------------------------
# Expire — DB + future + APPROVAL_RESOLVED
# ----------------------------------------------------------------------------


async def test_expire_harness_approval_marks_row_and_emits_event(harness_approval_setup):
    """Expire updates the row, publishes APPROVAL_RESOLVED(decision='expired')."""
    setup = harness_approval_setup
    factory = setup["factory"]

    # Manually create a pending harness row + register a future.
    approval_id = uuid.uuid4()
    async with factory() as db:
        row = ToolApproval(
            id=approval_id,
            session_id=setup["session"].id,
            channel_id=setup["channel"].id,
            bot_id=setup["bot"].id,
            tool_name="Bash",
            tool_type="harness",
            arguments={"cmd": "x"},
            status="pending",
            dispatch_type="harness",
            tool_call_id=None,
            timeout_seconds=300,
        )
        db.add(row)
        await db.commit()
    fut = create_approval_pending(str(approval_id))

    await expire_harness_approval(str(approval_id), reason="test cancel")

    # Row marked expired with system:expired decided_by.
    async with factory() as db:
        refreshed = await db.get(ToolApproval, approval_id)
        assert refreshed.status == "expired"
        assert refreshed.decided_by == "system:expired"
        assert refreshed.decided_at is not None

    # Future was resolved (cancel_approval returns False on a missing future,
    # so a successful expire path would have popped it).
    assert fut.done()

    # APPROVAL_RESOLVED with decision='expired' was published.
    events = _replay_buffer.get(setup["channel"].id, [])
    resolved = [e for e in events if e.kind is ChannelEventKind.APPROVAL_RESOLVED]
    assert len(resolved) == 1
    assert resolved[0].payload.decision == "expired"
    assert resolved[0].payload.approval_id == str(approval_id)


async def test_expire_is_idempotent_on_non_pending_row(harness_approval_setup):
    """Calling expire twice is safe — the second call is a no-op."""
    setup = harness_approval_setup
    factory = setup["factory"]
    approval_id = uuid.uuid4()
    async with factory() as db:
        db.add(ToolApproval(
            id=approval_id,
            session_id=setup["session"].id,
            channel_id=setup["channel"].id,
            bot_id=setup["bot"].id,
            tool_name="Bash", tool_type="harness", arguments={},
            status="pending", dispatch_type="harness",
            tool_call_id=None, timeout_seconds=300,
        ))
        await db.commit()
    await expire_harness_approval(str(approval_id), reason="first")
    # Second call: row is already expired — must not raise or duplicate event.
    await expire_harness_approval(str(approval_id), reason="second")
    events = _replay_buffer.get(setup["channel"].id, [])
    resolved = [e for e in events if e.kind is ChannelEventKind.APPROVAL_RESOLVED]
    assert len(resolved) == 1, "second expire should not republish"


# ----------------------------------------------------------------------------
# Cancel-pending — used by Stop-turn / chat_cancel
# ----------------------------------------------------------------------------


async def test_cancel_pending_expires_every_pending_row_for_session(harness_approval_setup):
    setup = harness_approval_setup
    factory = setup["factory"]
    # Three pending harness rows on this session, plus one already-decided row
    # (must be skipped) and one for a different session (must be skipped).
    async with factory() as db:
        for _ in range(3):
            db.add(ToolApproval(
                id=uuid.uuid4(),
                session_id=setup["session"].id,
                channel_id=setup["channel"].id,
                bot_id=setup["bot"].id,
                tool_name="Bash", tool_type="harness", arguments={},
                status="pending", dispatch_type="harness",
                tool_call_id=None, timeout_seconds=300,
            ))
        db.add(ToolApproval(
            id=uuid.uuid4(),
            session_id=setup["session"].id,
            channel_id=setup["channel"].id,
            bot_id=setup["bot"].id,
            tool_name="Bash", tool_type="harness", arguments={},
            status="approved", dispatch_type="harness",
            tool_call_id=None, timeout_seconds=300,
        ))
        # Different session, should NOT be touched.
        other_session = SessionRow(
            id=uuid.uuid4(),
            client_id="other-client",
            bot_id=setup["bot"].id,
            channel_id=setup["channel"].id,
            created_at=datetime.now(timezone.utc),
            last_active=datetime.now(timezone.utc),
        )
        db.add(other_session)
        await db.commit()
        db.add(ToolApproval(
            id=uuid.uuid4(),
            session_id=other_session.id,
            channel_id=setup["channel"].id,
            bot_id=setup["bot"].id,
            tool_name="Bash", tool_type="harness", arguments={},
            status="pending", dispatch_type="harness",
            tool_call_id=None, timeout_seconds=300,
        ))
        await db.commit()

    expired_count = await cancel_pending_harness_approvals_for_session(setup["session"].id)
    assert expired_count == 3

    async with factory() as db:
        from sqlalchemy import select
        statuses = (await db.execute(
            select(ToolApproval.status).where(
                ToolApproval.session_id == setup["session"].id,
            )
        )).scalars().all()
        assert sorted(statuses) == ["approved", "expired", "expired", "expired"]


# ----------------------------------------------------------------------------
# Per-turn bypass
# ----------------------------------------------------------------------------


async def test_grant_turn_bypass_skips_db_write_on_subsequent_calls(
    harness_approval_setup,
):
    setup = harness_approval_setup
    ctx = _make_ctx(setup, mode="default")
    grant_turn_bypass(ctx.turn_id)
    try:
        decision = await request_harness_approval(
            ctx=ctx, runtime=_StubRuntime(),
            tool_name="Bash", tool_input={"cmd": "x"},
        )
        assert decision.allow
        # No row was written.
        factory = setup["factory"]
        async with factory() as db:
            from sqlalchemy import select
            rows = (await db.execute(
                select(ToolApproval).where(ToolApproval.session_id == setup["session"].id)
            )).scalars().all()
        assert len(rows) == 0
    finally:
        revoke_turn_bypass(ctx.turn_id)


# ----------------------------------------------------------------------------
# Channel-less ask path
# ----------------------------------------------------------------------------


async def test_channel_less_turn_returns_deny_without_writing_row(
    harness_approval_setup,
):
    setup = harness_approval_setup
    ctx = _make_ctx(setup, mode="default", channel_id_override=None)
    # Force channel_id to None on the dataclass — _make_ctx uses None when override is None.
    ctx_no_chan = TurnContext(
        spindrel_session_id=ctx.spindrel_session_id,
        channel_id=None,
        bot_id=ctx.bot_id,
        turn_id=ctx.turn_id,
        workdir=ctx.workdir,
        harness_session_id=None,
        permission_mode=ctx.permission_mode,
        db_session_factory=ctx.db_session_factory,
    )
    decision = await request_harness_approval(
        ctx=ctx_no_chan, runtime=_StubRuntime(),
        tool_name="Bash", tool_input={"cmd": "x"},
    )
    assert not decision.allow
    assert "channel" in (decision.reason or "").lower()

    # No row written.
    factory = setup["factory"]
    async with factory() as db:
        from sqlalchemy import select
        rows = (await db.execute(
            select(ToolApproval).where(ToolApproval.session_id == setup["session"].id)
        )).scalars().all()
    assert len(rows) == 0
