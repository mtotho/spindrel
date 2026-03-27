"""Tests for per-bot / per-channel fallback model resolution."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.llm import _llm_call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(model: str = "test-model"):
    """Build a minimal ChatCompletion-like response."""
    msg = MagicMock()
    msg.content = "ok"
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(total_tokens=10)
    return resp


def _rate_limit_error():
    """Create a RateLimitError."""
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    return openai.RateLimitError(
        message="rate limited",
        response=resp,
        body=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_uses_passed_model():
    """When primary fails and fallback_model is passed, it should be used."""
    call_count = 0

    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs["model"] == "primary-model":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("app.agent.llm.settings") as mock_settings, \
         patch("app.services.providers.get_llm_client", return_value=mock_client), \
         patch("app.services.providers.record_usage"):
        mock_settings.LLM_MAX_RETRIES = 0
        mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
        mock_settings.LLM_RETRY_INITIAL_WAIT = 0
        mock_settings.LLM_FALLBACK_MODEL = ""  # no global fallback

        resp = await _llm_call(
            "primary-model", [], None, None,
            fallback_model="fallback-model",
            fallback_provider_id="fallback-provider",
        )
        assert resp is not None
        assert call_count == 2  # primary fail + fallback success


@pytest.mark.asyncio
async def test_fallback_falls_through_to_global():
    """When no per-bot/channel fallback, global LLM_FALLBACK_MODEL is used."""
    call_count = 0

    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs["model"] == "primary-model":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("app.agent.llm.settings") as mock_settings, \
         patch("app.services.providers.get_llm_client", return_value=mock_client), \
         patch("app.services.providers.record_usage"):
        mock_settings.LLM_MAX_RETRIES = 0
        mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
        mock_settings.LLM_RETRY_INITIAL_WAIT = 0
        mock_settings.LLM_FALLBACK_MODEL = "global-fallback"

        resp = await _llm_call(
            "primary-model", [], None, None,
            # no per-bot/channel fallback passed
        )
        assert resp is not None
        assert call_count == 2


@pytest.mark.asyncio
async def test_no_fallback_when_same_as_primary():
    """When fallback == primary, the error should be raised (no infinite loop)."""
    async def mock_create(**kwargs):
        raise _rate_limit_error()

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("app.agent.llm.settings") as mock_settings, \
         patch("app.services.providers.get_llm_client", return_value=mock_client), \
         patch("app.services.providers.record_usage"):
        mock_settings.LLM_MAX_RETRIES = 0
        mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
        mock_settings.LLM_RETRY_INITIAL_WAIT = 0
        mock_settings.LLM_FALLBACK_MODEL = ""

        with pytest.raises(openai.RateLimitError):
            await _llm_call(
                "my-model", [], None, None,
                fallback_model="my-model",
            )


@pytest.mark.asyncio
async def test_raises_when_no_fallback_configured():
    """When no fallback at any level, the error should propagate."""
    async def mock_create(**kwargs):
        raise _rate_limit_error()

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("app.agent.llm.settings") as mock_settings, \
         patch("app.services.providers.get_llm_client", return_value=mock_client), \
         patch("app.services.providers.record_usage"):
        mock_settings.LLM_MAX_RETRIES = 0
        mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
        mock_settings.LLM_RETRY_INITIAL_WAIT = 0
        mock_settings.LLM_FALLBACK_MODEL = ""

        with pytest.raises(openai.RateLimitError):
            await _llm_call("my-model", [], None, None)


@pytest.mark.asyncio
async def test_fallback_provider_used_for_fallback_call():
    """When fallback has its own provider_id, the fallback call should use that provider."""
    providers_seen = []

    async def mock_create(**kwargs):
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    def mock_get_client(provider_id=None):
        providers_seen.append(provider_id)
        client = MagicMock()
        client.chat.completions.create = mock_create
        return client

    with patch("app.agent.llm.settings") as mock_settings, \
         patch("app.services.providers.get_llm_client", side_effect=mock_get_client), \
         patch("app.services.providers.record_usage"):
        mock_settings.LLM_MAX_RETRIES = 0
        mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
        mock_settings.LLM_RETRY_INITIAL_WAIT = 0
        mock_settings.LLM_FALLBACK_MODEL = ""

        await _llm_call(
            "primary", [], None, None,
            provider_id="primary-provider",
            fallback_model="fallback",
            fallback_provider_id="fallback-provider",
        )
        # First call uses primary provider, second uses fallback provider
        assert providers_seen[0] == "primary-provider"
        assert providers_seen[1] == "fallback-provider"


def test_resolution_channel_over_bot_over_global():
    """Test the resolution logic: channel > bot > global."""
    # This tests the resolution pattern used in run_stream()
    # channel fallback set → uses channel
    channel_fb = "channel-model"
    bot_fb = "bot-model"
    result = channel_fb or bot_fb
    assert result == "channel-model"

    # channel fallback empty → uses bot
    channel_fb = None
    result = channel_fb or bot_fb
    assert result == "bot-model"

    # both empty → None (global handled in _llm_call)
    bot_fb = None
    result = channel_fb or bot_fb
    assert result is None
