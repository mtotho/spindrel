"""Phase N.6 — approval lifecycle extraction drift seams.

Drift-pin tests for the recently-extracted approval helpers:
  - ``app.agent.tool_dispatch._create_approval_state`` (atomic ToolCall +
    ToolApproval insert + fire-and-forget APPROVAL_REQUESTED publish)
  - ``app.agent.loop_dispatch._resolve_approval_verdict`` (timeout path
    expires pending rows, already-resolved rows return DB truth)

Existing `test_approval_orphan_pointers.py` + `test_loop_approval_race.py`
cover the happy-path contracts. This file covers the silent-default,
contextvar-propagation, and terminal-tool-call seams that a refactor could
regress without tripping those.

Seams pinned:
1. Empty ``extra_metadata={}`` collapses to NULL in the DB (``or None``
   shape). Distinguishes "no metadata supplied" from "caller wanted {}".
2. ``channel_id=None`` skips the fire-and-forget notification entirely —
   no ``safe_create_task`` scheduled, no log panic.
3. Dispatch ContextVars (``current_dispatch_type`` / ``current_dispatch_config``)
   propagate to the ToolApproval row at creation time.
4. ``policy_rule_id`` casts str → UUID; ``None`` stays ``None``.
5. Timeout path does NOT overwrite a tool_call row that has already
   advanced past ``awaiting_approval`` (running / denied / completed).
6. Timeout path with pending approval + no ``tool_call_id`` does not crash;
   only the approval row is expired.
7. Malformed ``approval_id`` string raises — contract pin, callers wrap in
   try/except (see ``_process_tool_call_result``'s existing catch).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.context import current_dispatch_config, current_dispatch_type
from app.agent.loop_dispatch import _resolve_approval_verdict
from app.agent.tool_dispatch import _create_approval_state
from app.db.models import ToolApproval, ToolCall

pytestmark = pytest.mark.asyncio


def _base_kw(**overrides):
    base = dict(
        session_id=uuid.uuid4(),
        channel_id=None,
        bot_id="drift-bot",
        client_id="drift-client",
        correlation_id=uuid.uuid4(),
        tool_name="write_file",
        tool_type="local",
        arguments={"path": "foo.txt"},
        iteration=0,
        policy_rule_id=None,
        reason="test gate",
        timeout=60,
        extra_metadata=None,
    )
    base.update(overrides)
    return base


class TestCreateApprovalStateSilentDefaults:
    async def test_empty_extra_metadata_collapses_to_null(
        self, db_session, patched_async_sessions
    ):
        """``extra_metadata={}`` → DB stores NULL via the ``or None`` shape."""
        await _create_approval_state(**_base_kw(extra_metadata={}))

        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.approval_metadata is None

    async def test_none_extra_metadata_stores_null(
        self, db_session, patched_async_sessions
    ):
        await _create_approval_state(**_base_kw(extra_metadata=None))

        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.approval_metadata is None

    async def test_populated_extra_metadata_persists_verbatim(
        self, db_session, patched_async_sessions
    ):
        await _create_approval_state(
            **_base_kw(extra_metadata={"tier": "exec", "source": "policy"})
        )

        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.approval_metadata == {"tier": "exec", "source": "policy"}


class TestCreateApprovalStateChannelFanout:
    async def test_channel_id_none_skips_notification_task(
        self, db_session, patched_async_sessions, monkeypatch
    ):
        """No channel_id → no ``safe_create_task`` fan-out. Approval still
        lands in the DB, so decide_approval routes still function without a
        channel binding.
        """
        scheduled: list = []
        from app.agent import tool_dispatch as td

        def spy(coro):
            scheduled.append(coro)
            coro.close()
            return None

        monkeypatch.setattr(td, "safe_create_task", spy)

        await _create_approval_state(**_base_kw(channel_id=None))

        assert scheduled == []
        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.channel_id is None

    async def test_channel_id_set_schedules_notification_task(
        self, db_session, patched_async_sessions, monkeypatch
    ):
        scheduled: list = []
        from app.agent import tool_dispatch as td

        def spy(coro):
            scheduled.append(coro)
            coro.close()
            return None

        monkeypatch.setattr(td, "safe_create_task", spy)

        channel_id = uuid.uuid4()
        await _create_approval_state(**_base_kw(channel_id=channel_id))

        assert len(scheduled) == 1


class TestCreateApprovalStateDispatchContextVars:
    async def test_dispatch_contextvars_propagate_to_row(
        self, db_session, patched_async_sessions
    ):
        token_type = current_dispatch_type.set("slack")
        token_cfg = current_dispatch_config.set({"channel": "#ops", "thread_ts": "123.456"})
        try:
            await _create_approval_state(**_base_kw())
        finally:
            current_dispatch_type.reset(token_type)
            current_dispatch_config.reset(token_cfg)

        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.dispatch_type == "slack"
        assert row.dispatch_metadata == {"channel": "#ops", "thread_ts": "123.456"}

    async def test_unset_contextvars_default_to_none(
        self, db_session, patched_async_sessions
    ):
        """ContextVars default to ``None`` when unset — rows carry ``None``
        rather than crashing on a missing default lookup.
        """
        await _create_approval_state(**_base_kw())

        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.dispatch_type is None
        assert row.dispatch_metadata is None


class TestCreateApprovalStatePolicyRuleCasting:
    async def test_policy_rule_id_string_is_cast_to_uuid(
        self, db_session, patched_async_sessions
    ):
        rule_uuid = uuid.uuid4()
        await _create_approval_state(**_base_kw(policy_rule_id=str(rule_uuid)))

        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.policy_rule_id == rule_uuid

    async def test_policy_rule_id_none_stays_none(
        self, db_session, patched_async_sessions
    ):
        await _create_approval_state(**_base_kw(policy_rule_id=None))

        row = (await db_session.execute(select(ToolApproval))).scalar_one()
        assert row.policy_rule_id is None


class TestResolveVerdictTerminalToolCallPreserved:
    async def test_timeout_does_not_overwrite_terminal_tool_call(
        self, db_session, patched_async_sessions
    ):
        """If the ToolCall already advanced past ``awaiting_approval`` (e.g.
        manually promoted to ``running`` for a retry path), timeout must NOT
        rewind it to ``expired`` — the approval row expires, the tool call
        keeps its terminal state.
        """
        tc = ToolCall(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            bot_id="drift-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={},
            status="running",
        )
        db_session.add(tc)
        appr = ToolApproval(
            id=uuid.uuid4(),
            bot_id="drift-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={},
            status="pending",
            tool_call_id=tc.id,
            timeout_seconds=300,
        )
        db_session.add(appr)
        await db_session.commit()
        appr_id, tc_id = appr.id, tc.id

        verdict = await _resolve_approval_verdict(str(appr_id), timeout_seconds=0.01)
        db_session.expire_all()

        appr_row = await db_session.get(ToolApproval, appr_id)
        tc_row = await db_session.get(ToolCall, tc_id)
        assert verdict == "expired"
        assert appr_row.status == "expired"
        assert tc_row.status == "running"  # untouched
        assert tc_row.completed_at is None


class TestResolveVerdictOrphanApproval:
    async def test_timeout_with_pending_approval_missing_tool_call_id_is_safe(
        self, db_session, patched_async_sessions
    ):
        """Approval row with ``tool_call_id=None`` — timeout still flips the
        approval to ``expired`` and doesn't attempt a ToolCall lookup.
        """
        appr = ToolApproval(
            id=uuid.uuid4(),
            bot_id="drift-bot",
            tool_name="write_file",
            tool_type="local",
            arguments={},
            status="pending",
            tool_call_id=None,
            timeout_seconds=300,
        )
        db_session.add(appr)
        await db_session.commit()
        appr_id = appr.id

        verdict = await _resolve_approval_verdict(str(appr_id), timeout_seconds=0.01)
        db_session.expire_all()

        appr_row = await db_session.get(ToolApproval, appr_id)
        assert verdict == "expired"
        assert appr_row.status == "expired"


class TestResolveVerdictBadUUIDContract:
    async def test_malformed_approval_id_raises(self, patched_async_sessions):
        """Contract: caller is responsible for catching bad UUIDs.
        ``_process_tool_call_result`` already wraps this in try/except and
        falls back to ``verdict = "expired"`` — pin the raise so a refactor
        that silently swallows it doesn't strand approvals.
        """
        with pytest.raises(ValueError):
            await _resolve_approval_verdict(
                "not-a-valid-uuid", timeout_seconds=0.01
            )
