from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent import task_run_host
from app.domain.errors import NotFoundError


@pytest.mark.asyncio
async def test_resolve_task_bot_refreshes_registry_once_for_runtime_created_bot(monkeypatch):
    bot = SimpleNamespace(id="runtime-bot")
    calls: list[str] = []

    def get_bot(bot_id: str):
        calls.append(bot_id)
        if len(calls) == 1:
            raise NotFoundError(f"Unknown bot: {bot_id}")
        return bot

    reload_bots = AsyncMock()
    monkeypatch.setattr("app.agent.bots.reload_bots", reload_bots)

    resolved = await task_run_host._resolve_task_bot(
        "runtime-bot",
        SimpleNamespace(get_bot=get_bot),
    )

    assert resolved is bot
    assert calls == ["runtime-bot", "runtime-bot"]
    reload_bots.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_task_bot_preserves_unknown_bot_error_after_refresh(monkeypatch):
    def get_bot(bot_id: str):
        raise NotFoundError(f"Unknown bot: {bot_id}")

    reload_bots = AsyncMock()
    monkeypatch.setattr("app.agent.bots.reload_bots", reload_bots)

    with pytest.raises(NotFoundError):
        await task_run_host._resolve_task_bot(
            "missing-bot",
            SimpleNamespace(get_bot=get_bot),
        )

    reload_bots.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_task_bot_refreshes_registry_for_unknown_bot_lookalike(monkeypatch):
    bot = SimpleNamespace(id="runtime-bot")
    calls = 0

    def get_bot(bot_id: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(f"Unknown bot: {bot_id}")
        return bot

    reload_bots = AsyncMock()
    monkeypatch.setattr("app.agent.bots.reload_bots", reload_bots)

    resolved = await task_run_host._resolve_task_bot(
        "runtime-bot",
        SimpleNamespace(get_bot=get_bot),
    )

    assert resolved is bot
    reload_bots.assert_awaited_once()
