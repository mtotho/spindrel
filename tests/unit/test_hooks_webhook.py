"""Tests for webhook emission in fire_hook / fire_hook_with_override."""
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


def _patch_urls(urls: str):
    """Patch HOOK_WEBHOOK_URLS on the real settings object."""
    return patch("app.config.settings.HOOK_WEBHOOK_URLS", urls)


@pytest.mark.asyncio
@patch("app.agent.hooks._post_webhook", new_callable=AsyncMock)
async def test_fire_hook_emits_webhook(mock_post):
    """fire_hook emits webhook when HOOK_WEBHOOK_URLS is set."""
    with _patch_urls("https://example.com/hook"):
        ctx = HookContext(bot_id="test-bot", extra={"tool_name": "web_search"})
        await fire_hook("after_tool_call", ctx)
        await asyncio.sleep(0)

        mock_post.assert_called_once()
        url, payload = mock_post.call_args.args
        assert url == "https://example.com/hook"
        assert payload["event"] == "after_tool_call"
        assert payload["context"]["bot_id"] == "test-bot"
        assert payload["data"]["tool_name"] == "web_search"
        assert "timestamp" in payload


@pytest.mark.asyncio
@patch("app.agent.hooks._post_webhook", new_callable=AsyncMock)
async def test_no_webhook_when_url_empty(mock_post):
    """No webhook when HOOK_WEBHOOK_URLS is empty."""
    with _patch_urls(""):
        await fire_hook("after_tool_call", HookContext(bot_id="test"))
        await asyncio.sleep(0)
        mock_post.assert_not_called()


@pytest.mark.asyncio
@patch("app.agent.hooks._post_webhook", new_callable=AsyncMock)
async def test_multiple_webhook_urls(mock_post):
    """Multiple comma-separated URLs all receive POST."""
    with _patch_urls("https://a.com/hook, https://b.com/hook"):
        await fire_hook("test_event", HookContext(bot_id="b"))
        await asyncio.sleep(0)

        assert mock_post.call_count == 2
        urls = {call.args[0] for call in mock_post.call_args_list}
        assert urls == {"https://a.com/hook", "https://b.com/hook"}


@pytest.mark.asyncio
async def test_webhook_failure_does_not_propagate():
    """Webhook POST failure doesn't propagate to fire_hook caller."""
    with _patch_urls("https://fail.example.com/hook"):
        with patch("app.agent.hooks._post_webhook", side_effect=Exception("network error")):
            # Should not raise
            await fire_hook("after_response", HookContext(bot_id="test"))
            await asyncio.sleep(0)


@pytest.mark.asyncio
@patch("app.agent.hooks._post_webhook", new_callable=AsyncMock)
async def test_webhook_payload_structure(mock_post):
    """Verify the full payload structure."""
    import uuid

    with _patch_urls("https://example.com/hook"):
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

        payload = mock_post.call_args.args[1]
        assert payload["event"] == "after_llm_call"
        assert payload["context"]["bot_id"] == "my-bot"
        assert payload["context"]["session_id"] == str(sid)
        assert payload["context"]["channel_id"] == str(cid)
        assert payload["context"]["client_id"] == "web:123"
        assert payload["context"]["correlation_id"] == str(corr)
        assert payload["data"]["model"] == "gpt-4"
        assert payload["data"]["duration_ms"] == 1234


@pytest.mark.asyncio
@patch("app.agent.hooks._post_webhook", new_callable=AsyncMock)
async def test_fire_hook_with_override_emits_webhook(mock_post):
    """fire_hook_with_override also emits webhooks."""
    with _patch_urls("https://example.com/hook"):
        result = await fire_hook_with_override("before_transcription", HookContext(
            extra={"audio_format": "webm", "audio_size_bytes": 1000, "source": "chat"},
        ))
        await asyncio.sleep(0)

        assert result is None
        mock_post.assert_called_once()
        payload = mock_post.call_args.args[1]
        assert payload["event"] == "before_transcription"
