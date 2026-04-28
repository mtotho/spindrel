"""Tests for the shared pending Future registry."""
from __future__ import annotations

import logging

import pytest

from app.agent.pending_registry import PendingRegistry


@pytest.mark.asyncio
async def test_registry_create_and_resolve() -> None:
    registry = PendingRegistry[str](label="test", logger=logging.getLogger(__name__))

    future = registry.create("req-1")

    assert registry.count() == 1
    assert registry.resolve("req-1", "done") is True
    assert future.result() == "done"
    assert registry.count() == 0


@pytest.mark.asyncio
async def test_registry_missing_and_already_done_paths() -> None:
    registry = PendingRegistry[str](label="test", logger=logging.getLogger(__name__))

    assert registry.resolve("missing", "done") is False
    future = registry.create("req-2")
    assert registry.resolve("req-2", "done") is True
    assert registry.resolve("req-2", "again") is False
    assert future.result() == "done"


@pytest.mark.asyncio
async def test_registry_cancel_and_discard_cleanup() -> None:
    registry = PendingRegistry[str](label="test", logger=logging.getLogger(__name__))

    cancel_future = registry.create("cancel")
    assert registry.cancel("cancel", "expired") is True
    assert cancel_future.result() == "expired"
    assert registry.count() == 0

    discard_future = registry.create("discard")
    assert registry.discard("discard") is True
    assert not discard_future.done()
    assert registry.count() == 0


@pytest.mark.asyncio
async def test_registry_clear() -> None:
    registry = PendingRegistry[str](label="test", logger=logging.getLogger(__name__))

    registry.create("a")
    registry.create("b")
    registry.clear()

    assert registry.count() == 0


@pytest.mark.asyncio
async def test_client_pending_wrapper_honors_patched_pending_dict(monkeypatch) -> None:
    from app.agent import pending

    patched: dict[str, object] = {}
    monkeypatch.setattr(pending, "_pending", patched)

    future = pending.create_pending("client-1")

    assert patched["client-1"] is future
    assert pending.pending_count() == 1
    assert pending.resolve_pending("client-1", "ok") is True
    assert patched == {}


@pytest.mark.asyncio
async def test_client_pending_expire_removes_without_resolving() -> None:
    from app.agent import pending

    pending.clear_pending()
    future = pending.create_pending("client-timeout")

    assert pending.expire_pending("client-timeout") is True
    assert pending.pending_count() == 0
    assert not future.done()
