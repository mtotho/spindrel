"""Tests for ordered fallback model chain in _llm_call."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.agent.llm import _llm_call, _model_cooldowns


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    """Ensure cooldowns don't leak between tests."""
    _model_cooldowns.clear()
    yield
    _model_cooldowns.clear()


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_fallback_used():
    """When primary fails and a single fallback is passed, it should be used."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call(
            "primary", [], None, None,
            fallback_models=[{"model": "fallback-1", "provider_id": None}],
        )
        assert resp is not None
        assert models_called == ["primary", "fallback-1"]


@pytest.mark.asyncio
async def test_chain_of_three_fallbacks():
    """When primary and first two fallbacks fail, third should succeed."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] in ("primary", "fb1", "fb2"):
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call(
            "primary", [], None, None,
            fallback_models=[
                {"model": "fb1"},
                {"model": "fb2"},
                {"model": "fb3"},
            ],
        )
        assert resp is not None
        assert models_called == ["primary", "fb1", "fb2", "fb3"]


@pytest.mark.asyncio
async def test_global_fallback_appended():
    """Global fallback list is appended after caller's list."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] in ("primary", "bot-fb"):
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    with _patched(global_fallbacks=[{"model": "global-fb", "provider_id": None}]) as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call(
            "primary", [], None, None,
            fallback_models=[{"model": "bot-fb"}],
        )
        assert resp is not None
        assert models_called == ["primary", "bot-fb", "global-fb"]


@pytest.mark.asyncio
async def test_global_only_when_no_caller_fallbacks():
    """When no caller fallbacks, global list is still used."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    with _patched(global_fallbacks=[{"model": "global-catch", "provider_id": None}]) as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call("primary", [], None, None)
        assert resp is not None
        assert models_called == ["primary", "global-catch"]


@pytest.mark.asyncio
async def test_dedup_primary_in_fallback_list():
    """Primary model appearing in fallback list should be skipped (no retry loop)."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] == "primary":
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call(
            "primary", [], None, None,
            fallback_models=[
                {"model": "primary"},  # should be skipped
                {"model": "actual-fallback"},
            ],
        )
        assert resp is not None
        assert models_called == ["primary", "actual-fallback"]


@pytest.mark.asyncio
async def test_dedup_between_caller_and_global():
    """Duplicate models between caller list and global should be skipped."""
    models_called = []

    async def mock_create(**kwargs):
        models_called.append(kwargs["model"])
        if kwargs["model"] in ("primary", "shared-fb"):
            raise _rate_limit_error()
        return _fake_response(kwargs["model"])

    with _patched(global_fallbacks=[
        {"model": "shared-fb"},  # already in caller list
        {"model": "global-only"},
    ]) as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        resp = await _llm_call(
            "primary", [], None, None,
            fallback_models=[{"model": "shared-fb"}],
        )
        assert resp is not None
        # shared-fb tried from caller list, NOT retried from global
        assert models_called == ["primary", "shared-fb", "global-only"]


@pytest.mark.asyncio
async def test_all_fallbacks_fail_raises():
    """When all fallbacks fail, the last error should be raised."""
    async def mock_create(**kwargs):
        raise _rate_limit_error()

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        with pytest.raises(openai.RateLimitError):
            await _llm_call(
                "primary", [], None, None,
                fallback_models=[{"model": "fb1"}, {"model": "fb2"}],
            )


@pytest.mark.asyncio
async def test_no_fallback_raises():
    """When no fallback at any level, the error should propagate."""
    async def mock_create(**kwargs):
        raise _rate_limit_error()

    with _patched() as (_, mock_get_client):
        client = MagicMock()
        client.chat.completions.create = mock_create
        mock_get_client.return_value = client

        with pytest.raises(openai.RateLimitError):
            await _llm_call("primary", [], None, None)


@pytest.mark.asyncio
async def test_fallback_provider_id_used():
    """Each fallback entry's provider_id should be passed to get_llm_client."""
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
         patch("app.services.providers.record_usage"), \
         patch("app.services.server_config.get_global_fallback_models", return_value=[]):
        mock_settings.LLM_MAX_RETRIES = 0
        mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
        mock_settings.LLM_RETRY_INITIAL_WAIT = 0
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 300

        await _llm_call(
            "primary", [], None, None,
            provider_id="primary-prov",
            fallback_models=[{"model": "fb", "provider_id": "fb-prov"}],
        )
        assert providers_seen[0] == "primary-prov"
        assert providers_seen[1] == "fb-prov"


@pytest.mark.asyncio
async def test_fallback_without_provider_id_auto_resolves():
    """When a fallback entry has no provider_id, the fallback model's own
    provider is auto-resolved via `resolve_provider_for_model`. Previously the
    primary's provider was inherited — that's how a Gemini fallback ended up
    dispatched to the Codex Responses endpoint.
    """
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

    def mock_resolve(model):
        # Fallback model advertises its own provider.
        return "fb-auto-prov" if model == "fb" else None

    with patch("app.agent.llm.settings") as mock_settings, \
         patch("app.services.providers.get_llm_client", side_effect=mock_get_client), \
         patch("app.services.providers.resolve_provider_for_model", side_effect=mock_resolve), \
         patch("app.services.providers.record_usage"), \
         patch("app.services.server_config.get_global_fallback_models", return_value=[]):
        mock_settings.LLM_MAX_RETRIES = 0
        mock_settings.LLM_RATE_LIMIT_INITIAL_WAIT = 0
        mock_settings.LLM_RETRY_INITIAL_WAIT = 0
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 300

        await _llm_call(
            "primary", [], None, None,
            provider_id="my-prov",
            fallback_models=[{"model": "fb"}],  # no provider_id
        )
        assert providers_seen[0] == "my-prov"
        assert providers_seen[1] == "fb-auto-prov"  # auto-resolved, NOT inherited


def test_resolution_channel_over_bot():
    """Test the resolution logic used in run_stream: channel list > bot list."""
    channel_fbs = [{"model": "ch-fb"}]
    bot_fbs = [{"model": "bot-fb"}]
    # channel set → uses channel
    result = channel_fbs or bot_fbs
    assert result == [{"model": "ch-fb"}]

    # channel empty → uses bot
    result = [] or bot_fbs
    assert result == [{"model": "bot-fb"}]

    # both empty → empty list (global appended in _llm_call)
    result = [] or []
    assert result == []
