"""Tests for webhook emission in fire_hook / fire_hook_with_override.

These tests verify that the hook system correctly delegates to the
DB-backed webhook service (app.services.webhooks.emit_webhooks).
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.hooks import (
    HookContext,
    _lifecycle_hooks,
    fire_hook,
    fire_hook_with_override,
)


@pytest.fixture(autouse=True)
def _clean_hooks():
    saved = {k: list(v) for k, v in _lifecycle_hooks.items()}
    _lifecycle_hooks.clear()
    yield
    _lifecycle_hooks.clear()
    _lifecycle_hooks.update(saved)


def _no_webhooks():
    """Patch emit_webhooks to be a no-op."""
    return patch("app.services.webhooks.emit_webhooks", new_callable=AsyncMock)


@pytest.mark.asyncio
async def test_fire_hook_emits_webhook():
    """fire_hook calls emit_webhooks with correct event and payload."""
    with _no_webhooks() as mock_emit:
        ctx = HookContext(bot_id="test-bot", extra={"tool_name": "web_search"})
        await fire_hook("after_tool_call", ctx)
        await asyncio.sleep(0)

        mock_emit.assert_called_once()
        event, payload = mock_emit.call_args.args
        assert event == "after_tool_call"
        assert payload["event"] == "after_tool_call"
        assert payload["context"]["bot_id"] == "test-bot"
        assert payload["data"]["tool_name"] == "web_search"
        assert "timestamp" in payload


@pytest.mark.asyncio
async def test_webhook_always_called():
    """emit_webhooks is always called (the service handles filtering internally)."""
    with _no_webhooks() as mock_emit:
        await fire_hook("after_tool_call", HookContext(bot_id="test"))
        await asyncio.sleep(0)
        mock_emit.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_payload_structure():
    """Verify the full payload structure passed to emit_webhooks."""
    import uuid

    with _no_webhooks() as mock_emit:
        sid = uuid.uuid4()
        cid = uuid.uuid4()
        corr = uuid.uuid4()
        ctx = HookContext(
            bot_id="my-bot",
            session_id=sid,
            channel_id=cid,
            client_id="web:123",
            correlation_id=corr,
            extra={"model": "gpt-4", "duration_ms": 1234},
        )
        await fire_hook("after_llm_call", ctx)
        await asyncio.sleep(0)

        payload = mock_emit.call_args.args[1]
        assert payload["event"] == "after_llm_call"
        assert payload["context"]["bot_id"] == "my-bot"
        assert payload["context"]["session_id"] == str(sid)
        assert payload["context"]["channel_id"] == str(cid)
        assert payload["context"]["client_id"] == "web:123"
        assert payload["context"]["correlation_id"] == str(corr)
        assert payload["data"]["model"] == "gpt-4"
        assert payload["data"]["duration_ms"] == 1234


@pytest.mark.asyncio
async def test_fire_hook_with_override_emits_webhook():
    """fire_hook_with_override also calls emit_webhooks."""
    with _no_webhooks() as mock_emit:
        result = await fire_hook_with_override("before_transcription", HookContext(
            extra={"audio_format": "webm", "audio_size_bytes": 1000, "source": "chat"},
        ))
        await asyncio.sleep(0)

        assert result is None
        mock_emit.assert_called_once()
        payload = mock_emit.call_args.args[1]
        assert payload["event"] == "before_transcription"


@pytest.mark.asyncio
async def test_webhook_failure_does_not_propagate():
    """Webhook service errors don't propagate to fire_hook caller."""
    with patch("app.services.webhooks.emit_webhooks", side_effect=Exception("network error")):
        # Should not raise — errors are swallowed by asyncio.create_task
        await fire_hook("after_response", HookContext(bot_id="test"))
        await asyncio.sleep(0)
