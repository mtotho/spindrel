"""Silent-failure semantics of ``app/agent/recording.py`` helpers.

``_start_tool_call`` / ``_complete_tool_call`` / ``_set_tool_call_status`` are
fire-and-forget writers: each one opens its own ``async_session()``, commits
its own transaction, and swallows exceptions via ``logger.exception``. Dispatch
calls them through ``safe_create_task``, so the caller can't await completion
and a missing update never raises.

That design has a failure mode the existing lifecycle test
(``test_tool_call_status_lifecycle.py``) doesn't exercise: UPDATE statements
targeting a row that never existed simply affect zero rows and commit quietly.
If ``_start_tool_call`` loses its commit race (or fails outright), the matching
``_complete_tool_call`` writes into the void and no one knows — the row stays
missing and every downstream consumer (the snapshot endpoint, the chat
rehydrate store, the trace detail UI) treats the call as if it never happened.

These tests pin that contract with real DB writes so the semantics are
explicit: any future hardening (logging missed UPDATEs, raising on zero
affected rows) has a regression surface it must move off of.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.recording import (
    _complete_tool_call,
    _record_tool_call,
    _set_tool_call_status,
    _start_tool_call,
)
from app.db.models import ToolCall


pytestmark = pytest.mark.asyncio


def _start_kwargs(**overrides) -> dict:
    base = dict(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        client_id=None,
        bot_id="test-bot",
        tool_name="read_file",
        tool_type="local",
        server_name=None,
        iteration=0,
        arguments={"path": "/x"},
        correlation_id=uuid.uuid4(),
    )
    base.update(overrides)
    return base


class TestCompleteOnMissingRow:
    async def test_complete_on_missing_row_is_silent_noop(
        self, db_session, patched_async_sessions,
    ):
        """If ``_start_tool_call`` never committed, ``_complete_tool_call`` affects 0 rows."""
        ghost_id = uuid.uuid4()

        await _complete_tool_call(
            ghost_id, result="ok", error=None, duration_ms=42, status="done",
        )

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert rows == []

    async def test_complete_after_start_updates_row_in_place(
        self, db_session, patched_async_sessions,
    ):
        """Normal lifecycle: INSERT at start, UPDATE at completion — single row."""
        kw = _start_kwargs()
        await _start_tool_call(**kw)
        await _complete_tool_call(
            kw["id"], result="done!", error=None, duration_ms=11, status="done",
        )

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == kw["id"]
        assert rows[0].status == "done"
        assert rows[0].result == "done!"
        assert rows[0].completed_at is not None


class TestCompleteTruncation:
    async def test_large_result_truncated_to_4000_by_default(
        self, db_session, patched_async_sessions,
    ):
        kw = _start_kwargs()
        await _start_tool_call(**kw)
        oversized = "x" * 9000

        await _complete_tool_call(
            kw["id"], result=oversized, error=None, duration_ms=1, status="done",
        )

        row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert len(row.result) == 4000

    async def test_store_full_result_keeps_full_output(
        self, db_session, patched_async_sessions,
    ):
        """When the dispatcher summarized or hard-capped, the full original is kept."""
        kw = _start_kwargs()
        await _start_tool_call(**kw)
        oversized = "y" * 12000

        await _complete_tool_call(
            kw["id"], result=oversized, error=None, duration_ms=1,
            status="done", store_full_result=True,
        )

        row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert len(row.result) == 12000


class TestSetStatusSemantics:
    async def test_set_status_on_missing_row_is_silent_noop(
        self, db_session, patched_async_sessions,
    ):
        await _set_tool_call_status(uuid.uuid4(), "running")

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert rows == []

    async def test_set_status_has_no_state_machine_guard(
        self, db_session, patched_async_sessions,
    ):
        """Any transition is accepted — the helper is dumb; callers own the policy.

        ``decide_approval`` guards by checking status before calling; this
        helper will happily flip ``done`` back to ``awaiting_approval`` if
        asked. Documents the contract so any future tightening is explicit.
        """
        kw = _start_kwargs()
        await _start_tool_call(**kw)
        await _complete_tool_call(
            kw["id"], result="r", error=None, duration_ms=1, status="done",
        )

        await _set_tool_call_status(kw["id"], "awaiting_approval")

        row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert row.status == "awaiting_approval"


class TestStartAndRecordExceptionSwallow:
    async def test_duplicate_start_is_swallowed_not_raised(
        self, db_session, patched_async_sessions,
    ):
        """Second ``_start_tool_call`` with the same id hits the PK unique and logs."""
        kw = _start_kwargs()
        await _start_tool_call(**kw)

        # No pytest.raises — the helper must swallow the integrity error.
        await _start_tool_call(**kw)

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert len(rows) == 1

    async def test_record_tool_call_inserts_terminal_row_directly(
        self, db_session, patched_async_sessions,
    ):
        """Auth/policy denials never call start/complete — they go straight to terminal."""
        await _record_tool_call(
            session_id=uuid.uuid4(),
            client_id=None,
            bot_id="test-bot",
            tool_name="blocked_tool",
            tool_type="local",
            server_name=None,
            iteration=0,
            arguments={},
            result='{"error": "denied"}',
            error="denied by policy",
            duration_ms=0,
            status="denied",
        )

        row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert row.status == "denied"
        assert row.completed_at is not None
        assert row.error == "denied by policy"
