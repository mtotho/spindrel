"""Failure-handling semantics of ``app/agent/recording.py`` helpers."""
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


class TestMissingRowUpdates:
    async def test_complete_on_missing_row_returns_false_by_default(
        self, db_session, patched_async_sessions,
    ):
        updated = await _complete_tool_call(
            uuid.uuid4(),
            result="ok",
            error=None,
            duration_ms=42,
            status="done",
        )

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert updated is False
        assert rows == []

    async def test_complete_on_missing_row_raises_in_strict_mode(
        self, patched_async_sessions,
    ):
        with pytest.raises(RuntimeError, match="missing during completion"):
            await _complete_tool_call(
                uuid.uuid4(),
                result="ok",
                error=None,
                duration_ms=42,
                status="done",
                strict=True,
            )

    async def test_set_status_on_missing_row_returns_false_by_default(
        self, db_session, patched_async_sessions,
    ):
        updated = await _set_tool_call_status(uuid.uuid4(), "running")

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert updated is False
        assert rows == []

    async def test_set_status_on_missing_row_raises_in_strict_mode(
        self, patched_async_sessions,
    ):
        with pytest.raises(RuntimeError, match="missing during status update"):
            await _set_tool_call_status(uuid.uuid4(), "running", strict=True)


class TestLifecycle:
    async def test_complete_after_start_updates_row_in_place(
        self, db_session, patched_async_sessions,
    ):
        kw = _start_kwargs()
        started = await _start_tool_call(**kw)
        completed = await _complete_tool_call(
            kw["id"], result="done!", error=None, duration_ms=11, status="done",
        )

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert started is True
        assert completed is True
        assert len(rows) == 1
        assert rows[0].id == kw["id"]
        assert rows[0].status == "done"
        assert rows[0].result == "done!"
        assert rows[0].completed_at is not None

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
        kw = _start_kwargs()
        await _start_tool_call(**kw)
        oversized = "y" * 12000

        await _complete_tool_call(
            kw["id"], result=oversized, error=None, duration_ms=1,
            status="done", store_full_result=True,
        )

        row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert len(row.result) == 12000

    async def test_set_status_still_allows_direct_transitions(
        self, db_session, patched_async_sessions,
    ):
        kw = _start_kwargs()
        await _start_tool_call(**kw)
        await _complete_tool_call(
            kw["id"], result="r", error=None, duration_ms=1, status="done",
        )

        updated = await _set_tool_call_status(kw["id"], "awaiting_approval")

        row = (await db_session.execute(select(ToolCall))).scalar_one()
        assert updated is True
        assert row.status == "awaiting_approval"


class TestExceptionHandling:
    async def test_duplicate_start_returns_false_by_default(
        self, db_session, patched_async_sessions,
    ):
        kw = _start_kwargs()
        assert await _start_tool_call(**kw) is True

        duplicate = await _start_tool_call(**kw)

        rows = (await db_session.execute(select(ToolCall))).scalars().all()
        assert duplicate is False
        assert len(rows) == 1

    async def test_duplicate_start_raises_in_strict_mode(
        self, patched_async_sessions,
    ):
        kw = _start_kwargs()
        await _start_tool_call(**kw)

        with pytest.raises(Exception):
            await _start_tool_call(**kw, strict=True)

    async def test_record_tool_call_inserts_terminal_row_directly(
        self, db_session, patched_async_sessions,
    ):
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
