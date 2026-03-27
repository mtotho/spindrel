"""Unit tests for the approval pending system."""
import asyncio

import pytest

from app.agent.approval_pending import (
    _pending,
    cancel_approval,
    create_approval_pending,
    pending_count,
    resolve_approval,
)


@pytest.fixture(autouse=True)
def clear_pending():
    _pending.clear()
    yield
    _pending.clear()


class TestApprovalPending:
    @pytest.mark.asyncio
    async def test_create_and_resolve(self):
        future = create_approval_pending("ap-1")
        assert pending_count() == 1
        assert not future.done()

        ok = resolve_approval("ap-1", "approved")
        assert ok is True
        assert future.done()
        assert future.result() == "approved"
        assert pending_count() == 0

    @pytest.mark.asyncio
    async def test_resolve_nonexistent(self):
        ok = resolve_approval("doesnt-exist", "approved")
        assert ok is False

    @pytest.mark.asyncio
    async def test_resolve_already_done(self):
        future = create_approval_pending("ap-2")
        resolve_approval("ap-2", "approved")

        # Re-create with same id to test double resolution
        future2 = create_approval_pending("ap-3")
        resolve_approval("ap-3", "approved")
        ok = resolve_approval("ap-3", "denied")
        assert ok is False  # already resolved and removed

    @pytest.mark.asyncio
    async def test_cancel(self):
        future = create_approval_pending("ap-4")
        ok = cancel_approval("ap-4")
        assert ok is True
        assert future.done()
        assert future.result() == "expired"
        assert pending_count() == 0

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self):
        ok = cancel_approval("doesnt-exist")
        assert ok is False

    @pytest.mark.asyncio
    async def test_multiple_pending(self):
        f1 = create_approval_pending("a1")
        f2 = create_approval_pending("a2")
        f3 = create_approval_pending("a3")
        assert pending_count() == 3

        resolve_approval("a2", "denied")
        assert pending_count() == 2
        assert f2.result() == "denied"
        assert not f1.done()
        assert not f3.done()


class TestToolCallResultApprovalFields:
    def test_default_fields(self):
        from app.agent.tool_dispatch import ToolCallResult
        result = ToolCallResult()
        assert result.needs_approval is False
        assert result.approval_id is None
        assert result.approval_timeout == 300
        assert result.approval_reason is None

    def test_approval_fields_set(self):
        from app.agent.tool_dispatch import ToolCallResult
        result = ToolCallResult(
            needs_approval=True,
            approval_id="test-id",
            approval_timeout=600,
            approval_reason="Destructive command",
        )
        assert result.needs_approval is True
        assert result.approval_id == "test-id"
        assert result.approval_timeout == 600
