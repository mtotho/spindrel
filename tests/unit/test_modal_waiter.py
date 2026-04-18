"""Tests for the modal waiter + submit/cancel lifecycle."""
from __future__ import annotations

import asyncio

import pytest

from app.services import modal_waiter

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    modal_waiter.reset()
    yield
    modal_waiter.reset()


class TestRegister:
    def test_generates_callback_id(self):
        cid = modal_waiter.register()
        assert cid and isinstance(cid, str)
        assert modal_waiter.pending_count() == 1

    def test_accepts_explicit_callback_id(self):
        cid = modal_waiter.register("chosen-id")
        assert cid == "chosen-id"

    def test_collision_raises(self):
        modal_waiter.register("dup")
        with pytest.raises(ValueError):
            modal_waiter.register("dup")


class TestSubmit:
    async def test_resolves_waiter_with_values(self):
        cid = modal_waiter.register()

        async def waiter():
            return await modal_waiter.wait(cid, timeout=5.0)

        task = asyncio.create_task(waiter())
        # Give the waiter a tick to register its future.
        await asyncio.sleep(0)
        ok = modal_waiter.submit(
            cid, values={"name": "alice"}, submitted_by="UA", metadata={"source": "slack"},
        )
        assert ok is True

        result = await asyncio.wait_for(task, timeout=1.0)
        assert result["ok"] is True
        assert result["values"] == {"name": "alice"}
        assert result["submitted_by"] == "UA"
        assert result["metadata"] == {"source": "slack"}

    async def test_submit_without_waiter_returns_false(self):
        ok = modal_waiter.submit("missing", values={}, submitted_by="x")
        assert ok is False

    async def test_slot_cleaned_up_after_wait(self):
        cid = modal_waiter.register()
        assert modal_waiter.pending_count() == 1
        modal_waiter.submit(cid, values={}, submitted_by="x")
        await modal_waiter.wait(cid, timeout=1.0)
        assert modal_waiter.pending_count() == 0


class TestCancel:
    async def test_cancel_resolves_with_error(self):
        cid = modal_waiter.register()

        async def waiter():
            return await modal_waiter.wait(cid, timeout=5.0)

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        modal_waiter.cancel(cid, reason="user_dismissed")

        result = await asyncio.wait_for(task, timeout=1.0)
        assert result["ok"] is False
        assert result["error"] == "user_dismissed"

    async def test_cancel_on_missing_callback_is_noop(self):
        modal_waiter.cancel("missing", reason="x")


class TestTimeout:
    async def test_timeout_drains_slot_and_reports_error(self):
        cid = modal_waiter.register()
        result = await modal_waiter.wait(cid, timeout=0.05)
        assert result["ok"] is False
        assert result["error"] == "modal timed out"
        assert modal_waiter.pending_count() == 0
