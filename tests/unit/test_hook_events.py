"""Tests for new hook events: before_llm_call, after_llm_call, before_tool_execution, before_transcription."""
from unittest.mock import patch

import pytest

from app.agent.hooks import (
    HookContext,
    _lifecycle_hooks,
    fire_hook,
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
    return patch("app.config.settings.HOOK_WEBHOOK_URLS", "")


@pytest.mark.asyncio
async def test_before_llm_call_extra_data():
    """before_llm_call fires with correct extra data fields."""
    with _no_webhooks():
        captured = []

        async def _on_before_llm(ctx, **kwargs):
            captured.append(ctx.extra)

        register_hook("before_llm_call", _on_before_llm)

        ctx = HookContext(
            bot_id="test-bot",
            extra={
                "model": "gpt-4",
                "message_count": 5,
                "tools_count": 3,
                "provider_id": "openai-1",
                "iteration": 1,
            },
        )
        await fire_hook("before_llm_call", ctx)

        assert len(captured) == 1
        assert captured[0]["model"] == "gpt-4"
        assert captured[0]["message_count"] == 5
        assert captured[0]["tools_count"] == 3
        assert captured[0]["provider_id"] == "openai-1"
        assert captured[0]["iteration"] == 1


@pytest.mark.asyncio
async def test_after_llm_call_extra_data():
    """after_llm_call fires with usage and fallback data."""
    with _no_webhooks():
        captured = []

        async def _on_after_llm(ctx, **kwargs):
            captured.append(ctx.extra)

        register_hook("after_llm_call", _on_after_llm)

        ctx = HookContext(
            bot_id="test-bot",
            extra={
                "model": "gpt-4",
                "duration_ms": 1500,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "tool_calls_count": 2,
                "fallback_used": False,
                "fallback_model": None,
                "iteration": 1,
                "provider_id": "openai-1",
            },
        )
        await fire_hook("after_llm_call", ctx)

        assert len(captured) == 1
        assert captured[0]["duration_ms"] == 1500
        assert captured[0]["prompt_tokens"] == 100
        assert captured[0]["completion_tokens"] == 50
        assert captured[0]["total_tokens"] == 150
        assert captured[0]["tool_calls_count"] == 2
        assert captured[0]["fallback_used"] is False
        assert captured[0]["fallback_model"] is None


@pytest.mark.asyncio
async def test_before_tool_execution_fires_with_data():
    """before_tool_execution fires with tool_name, tool_type, args, iteration."""
    with _no_webhooks():
        captured = []

        async def _on_before_tool(ctx, **kwargs):
            captured.append(ctx.extra)

        register_hook("before_tool_execution", _on_before_tool)

        ctx = HookContext(
            bot_id="test-bot",
            extra={
                "tool_name": "web_search",
                "tool_type": "local",
                "args": '{"query": "hello"}',
                "iteration": 1,
            },
        )
        await fire_hook("before_tool_execution", ctx)

        assert len(captured) == 1
        assert captured[0]["tool_name"] == "web_search"
        assert captured[0]["tool_type"] == "local"
        assert captured[0]["iteration"] == 1


@pytest.mark.asyncio
async def test_before_transcription_override_short_circuits():
    """before_transcription override returns custom transcript."""
    with _no_webhooks():
        async def _custom_stt(ctx, **kwargs):
            return "custom transcription result"

        register_hook("before_transcription", _custom_stt)

        result = await fire_hook_with_override("before_transcription", HookContext(
            extra={
                "audio_format": "webm",
                "audio_size_bytes": 5000,
                "source": "chat",
            },
        ))

        assert result == "custom transcription result"


@pytest.mark.asyncio
async def test_before_transcription_no_override():
    """before_transcription returns None when no override provided."""
    with _no_webhooks():
        async def _noop(ctx, **kwargs):
            return None

        register_hook("before_transcription", _noop)

        result = await fire_hook_with_override("before_transcription", HookContext(
            extra={"audio_format": "m4a", "audio_size_bytes": 1000, "source": "api"},
        ))

        assert result is None
