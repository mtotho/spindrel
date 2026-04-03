"""Tests for the model fallback circuit breaker."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.llm import (
    AccumulatedMessage,
    _llm_call,
    _llm_call_stream,
    _model_cooldowns,
    clear_model_cooldown,
    get_active_cooldowns,
    get_cooldown_expiry,
    get_model_cooldown,
    set_model_cooldown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(model: str = "test-model"):
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
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    return openai.RateLimitError(message="rate limited", response=resp, body=None)


def _fake_stream_chunk(content="ok", finish_reason="stop"):
    """Build a minimal streaming chunk."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = None
    delta.reasoning_content = None
    delta.reasoning = None
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = MagicMock(total_tokens=10)
    return chunk


async def _fake_stream_iter():
    """Async iterator that yields one chunk."""
    yield _fake_stream_chunk()


def _patched(global_fallbacks=None):
    """Context manager that patches settings, providers, and global fallback cache."""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        with patch("app.agent.llm.settings") as mock_settings, \
             patch("app.services.providers.get_llm_client") as mock_get_client, \
             patch("app.services.providers.record_usage"), \
             patch("app.services.server_config.get_global_fallback_models",
                   return_value=global_fallbacks or []):
            mock_settings.LLM_MAX_RETRIES = 0
            mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
            mock_settings.LLM_RETRY_INITIAL_WAIT = 0
            mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 300
            yield mock_settings, mock_get_client
    return ctx()


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    """Ensure cooldowns are cleared before and after each test."""
    _model_cooldowns.clear()
    yield
    _model_cooldowns.clear()


# ---------------------------------------------------------------------------
# Unit tests for cooldown helpers
# ---------------------------------------------------------------------------

def test_set_and_get_cooldown():
    with patch("app.agent.llm.settings") as mock_settings:
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 300
        set_model_cooldown("broken-model", "good-model")

    fb_model, fb_provider = get_model_cooldown("broken-model")
    assert fb_model == "good-model"
    assert fb_provider is None  # no provider stored


def test_cooldown_stores_provider():
    with patch("app.agent.llm.settings") as mock_settings:
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 300
        set_model_cooldown("broken-model", "good-model", provider_id="anthropic-prod")

    fb_model, fb_provider = get_model_cooldown("broken-model")
    assert fb_model == "good-model"
    assert fb_provider == "anthropic-prod"


def test_cooldown_not_set_when_zero():
    with patch("app.agent.llm.settings") as mock_settings:
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 0
        set_model_cooldown("broken-model", "good-model")

    assert get_model_cooldown("broken-model") is None


def test_cooldown_expires():
    _model_cooldowns["old-model"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1),
        "fallback",
        None,
    )
    assert get_model_cooldown("old-model") is None
    assert "old-model" not in _model_cooldowns


def test_clear_cooldown():
    _model_cooldowns["some-model"] = (
        datetime.now(timezone.utc) + timedelta(seconds=300),
        "fallback",
        None,
    )
    assert clear_model_cooldown("some-model") is True
    assert clear_model_cooldown("some-model") is False


def test_get_active_cooldowns():
    now = datetime.now(timezone.utc)
    _model_cooldowns["active"] = (now + timedelta(seconds=100), "fb-1", None)
    _model_cooldowns["expired"] = (now - timedelta(seconds=1), "fb-2", None)

    active = get_active_cooldowns()
    assert len(active) == 1
    assert active[0]["model"] == "active"
    assert active[0]["fallback_model"] == "fb-1"
    assert active[0]["remaining_seconds"] > 0
    assert "expired" not in _model_cooldowns


def test_get_model_cooldown_nonexistent():
    assert get_model_cooldown("never-seen") is None


def test_get_cooldown_expiry():
    expires = datetime.now(timezone.utc) + timedelta(seconds=300)
    _model_cooldowns["model-x"] = (expires, "fb", None)
    assert get_cooldown_expiry("model-x") == expires


def test_get_cooldown_expiry_expired():
    _model_cooldowns["model-x"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1), "fb", None,
    )
    assert get_cooldown_expiry("model-x") is None
    assert "model-x" not in _model_cooldowns


def test_get_cooldown_expiry_nonexistent():
    assert get_cooldown_expiry("no-such-model") is None


# ---------------------------------------------------------------------------
# Integration: circuit breaker in _llm_call (non-streaming)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cooldown_skips_primary():
    """When a model is in cooldown, _llm_call should skip it and use the fallback directly."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        return _fake_response(kwargs["model"])

    _model_cooldowns["primary"] = (
        datetime.now(timezone.utc) + timedelta(seconds=300),
        "fallback-model",
        None,
    )

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call("primary", [], None, None)
        assert resp is not None
        assert models_called == ["fallback-model"]


@pytest.mark.asyncio
async def test_cooldown_uses_stored_provider():
    """Cooldown bypass should use the fallback's stored provider_id, not the primary's."""
    providers_called = []

    async def mock_create(**kwargs):
        return _fake_response(kwargs["model"])

    _model_cooldowns["primary"] = (
        datetime.now(timezone.utc) + timedelta(seconds=300),
        "fallback-model",
        "anthropic-prod",
    )

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.side_effect = lambda pid: (providers_called.append(pid), client)[1]

        resp = await _llm_call("primary", [], None, "openai-prod")
        assert resp is not None
        # Should have called get_llm_client with the stored fallback provider
        assert "anthropic-prod" in providers_called


@pytest.mark.asyncio
async def test_cooldown_failure_skips_primary_goes_to_fallback_chain():
    """When cooldown fallback fails, should NOT retry the broken primary — go to fallback chain."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] == "cooldown-fb":
            raise _rate_limit_error()
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    _model_cooldowns["primary"] = (
        datetime.now(timezone.utc) + timedelta(seconds=300),
        "cooldown-fb",
        None,
    )

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call(
            "primary", [], None, None,
            fallback_models=[{"model": "chain-fb"}],
        )
        assert resp is not None
        # cooldown-fb fails → skip primary → chain-fb succeeds
        assert models_called == ["cooldown-fb", "chain-fb"]
        # "primary" should NOT appear in calls
        assert "primary" not in models_called


@pytest.mark.asyncio
async def test_fallback_sets_cooldown():
    """When a fallback succeeds after primary failure, a cooldown should be set."""
    async def mock_create(**kwargs):
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call(
            "primary", [], None, None,
            fallback_models=[{"model": "good-fallback"}],
        )
        assert resp is not None
        fb_model, _ = get_model_cooldown("primary")
        assert fb_model == "good-fallback"


# ---------------------------------------------------------------------------
# Integration: circuit breaker in _llm_call_stream (streaming)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_cooldown_skips_primary():
    """Streaming path: model in cooldown should skip directly to fallback."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        return _fake_stream_iter()

    _model_cooldowns["primary"] = (
        datetime.now(timezone.utc) + timedelta(seconds=300),
        "fallback-model",
        None,
    )

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        events = []
        async for item in _llm_call_stream("primary", [], None, None):
            events.append(item)

        assert models_called == ["fallback-model"]
        # Should have a cooldown_skip event
        assert any(
            isinstance(e, dict) and e.get("type") == "llm_cooldown_skip"
            for e in events
        )
        # Last item should be AccumulatedMessage
        assert isinstance(events[-1], AccumulatedMessage)


@pytest.mark.asyncio
async def test_stream_cooldown_failure_skips_primary():
    """Streaming path: when cooldown fallback fails, should skip primary and go to fallback chain."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] == "cooldown-fb":
            raise _rate_limit_error()
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_stream_iter()

    _model_cooldowns["primary"] = (
        datetime.now(timezone.utc) + timedelta(seconds=300),
        "cooldown-fb",
        None,
    )

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        events = []
        async for item in _llm_call_stream(
            "primary", [], None, None,
            fallback_models=[{"model": "chain-fb"}],
        ):
            events.append(item)

        # cooldown-fb fails → skip primary → chain-fb succeeds
        assert models_called == ["cooldown-fb", "chain-fb"]
        assert "primary" not in models_called
        assert isinstance(events[-1], AccumulatedMessage)


@pytest.mark.asyncio
async def test_stream_fallback_sets_cooldown():
    """Streaming path: successful fallback should set a cooldown."""
    async def mock_create(**kwargs):
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_stream_iter()

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        events = []
        async for item in _llm_call_stream(
            "primary", [], None, None,
            fallback_models=[{"model": "good-fb"}],
        ):
            events.append(item)

        assert isinstance(events[-1], AccumulatedMessage)
        fb_model, _ = get_model_cooldown("primary")
        assert fb_model == "good-fb"
