"""Tests for fire_hook_with_override (override-capable hooks)."""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.hooks import (
    HookContext,
    _lifecycle_hooks,
    fire_hook_with_override,
    register_hook,
)


@pytest.fixture(autouse=True)
def _clean_hooks():
    saved = {k: list(v) for k, v in _lifecycle_hooks.items()}
    _lifecycle_hooks.clear()
    yield
    _lifecycle_hooks.clear()
    _lifecycle_hooks.update(saved)


def _no_webhooks():
    return patch("app.services.webhooks.emit_webhooks", new_callable=AsyncMock)


@pytest.mark.asyncio
async def test_returns_first_non_none():
    """fire_hook_with_override returns the first non-None result."""
    with _no_webhooks():
        async def _provider_a(ctx, **kwargs):
            return None

        async def _provider_b(ctx, **kwargs):
            return "transcribed by B"

        register_hook("before_transcription", _provider_a)
        register_hook("before_transcription", _provider_b)

        result = await fire_hook_with_override("before_transcription", HookContext())
        assert result == "transcribed by B"


@pytest.mark.asyncio
async def test_returns_none_when_all_none():
    """Returns None when all callbacks return None."""
    with _no_webhooks():
        async def _noop(ctx, **kwargs):
            return None

        register_hook("before_transcription", _noop)

        result = await fire_hook_with_override("before_transcription", HookContext())
        assert result is None


@pytest.mark.asyncio
async def test_short_circuits():
    """Later callbacks don't run after a non-None return."""
    with _no_webhooks():
        calls = []

        async def _first(ctx, **kwargs):
            calls.append("first")
            return "override"

        async def _second(ctx, **kwargs):
            calls.append("second")
            return "also override"

        register_hook("before_transcription", _first)
        register_hook("before_transcription", _second)

        result = await fire_hook_with_override("before_transcription", HookContext())
        assert result == "override"
        assert calls == ["first"]


@pytest.mark.asyncio
async def test_swallows_callback_errors():
    """Errors in callbacks are swallowed, next callback runs."""
    with _no_webhooks():
        async def _bad(ctx, **kwargs):
            raise RuntimeError("boom")

        async def _good(ctx, **kwargs):
            return "fallback"

        register_hook("before_transcription", _bad)
        register_hook("before_transcription", _good)

        result = await fire_hook_with_override("before_transcription", HookContext())
        assert result == "fallback"


@pytest.mark.asyncio
async def test_works_with_sync_callbacks():
    """Sync callbacks also work with fire_hook_with_override."""
    with _no_webhooks():
        def _sync_provider(ctx, **kwargs):
            return "sync result"

        register_hook("before_transcription", _sync_provider)

        result = await fire_hook_with_override("before_transcription", HookContext())
        assert result == "sync result"


@pytest.mark.asyncio
async def test_no_callbacks_returns_none():
    """No callbacks registered returns None."""
    with _no_webhooks():
        result = await fire_hook_with_override("nonexistent_event", HookContext())
        assert result is None
