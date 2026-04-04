"""Tests for POST /api/v1/llm/completions endpoint."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_completion(content: str = "Hello!", model: str = "gpt-4o-mini"):
    """Build a fake OpenAI-style completion response."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], model=model, usage=usage)


HEADERS = {"Authorization": "Bearer test-key"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completions_success():
    """Successful completion returns content, model, and usage."""
    fake_resp = _fake_completion("Hi there!", "gpt-4o-mini")
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with (
        patch("app.services.providers.resolve_provider_for_model", return_value=None),
        patch("app.services.providers.get_llm_client", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/llm/completions", json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hello"}],
            }, headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Hi there!"
    assert data["model"] == "gpt-4o-mini"
    assert data["usage"]["total_tokens"] == 15


@pytest.mark.asyncio
async def test_completions_no_model_uses_default():
    """When model is omitted, DEFAULT_MODEL should be used."""
    fake_resp = _fake_completion("response", "default-model")
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with (
        patch("app.routers.api_v1_llm.settings") as mock_settings,
        patch("app.services.providers.resolve_provider_for_model", return_value=None),
        patch("app.services.providers.get_llm_client", return_value=mock_client),
    ):
        mock_settings.DEFAULT_MODEL = "default-model"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/llm/completions", json={
                "messages": [{"role": "user", "content": "Hi"}],
            }, headers=HEADERS)

    assert resp.status_code == 200
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "default-model"


@pytest.mark.asyncio
async def test_completions_llm_error_returns_502():
    """LLM call failure should return 502."""
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("rate limited"))

    with (
        patch("app.services.providers.resolve_provider_for_model", return_value=None),
        patch("app.services.providers.get_llm_client", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/llm/completions", json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hello"}],
            }, headers=HEADERS)

    assert resp.status_code == 502
    assert "rate limited" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_completions_empty_messages_rejected():
    """Empty messages list should be rejected by validation."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/llm/completions", json={
            "model": "gpt-4o-mini",
            "messages": [],
        }, headers=HEADERS)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_completions_temperature_and_max_tokens():
    """Optional temperature and max_tokens should be forwarded."""
    fake_resp = _fake_completion("ok")
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with (
        patch("app.services.providers.resolve_provider_for_model", return_value=None),
        patch("app.services.providers.get_llm_client", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/llm/completions", json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hi"}],
                "temperature": 0.5,
                "max_tokens": 100,
            }, headers=HEADERS)

    assert resp.status_code == 200
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.5
    assert call_kwargs["max_tokens"] == 100


@pytest.mark.asyncio
async def test_completions_no_auth_returns_401():
    """Missing auth header should return 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/llm/completions", json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
        })

    assert resp.status_code == 422 or resp.status_code == 401


@pytest.mark.asyncio
async def test_completions_no_usage_returns_null():
    """When LLM response has no usage, usage should be null."""
    message = SimpleNamespace(content="hi")
    choice = SimpleNamespace(message=message)
    fake_resp = SimpleNamespace(choices=[choice], model="gpt-4o-mini", usage=None)
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with (
        patch("app.services.providers.resolve_provider_for_model", return_value=None),
        patch("app.services.providers.get_llm_client", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/llm/completions", json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hi"}],
            }, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["usage"] is None


@pytest.mark.asyncio
async def test_completions_records_usage_trace():
    """Successful completion should fire a TraceEvent for usage tracking."""
    fake_resp = _fake_completion("Hi!", "gpt-4o-mini")
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    captured_coro = None

    def capture_safe_create_task(coro, **kwargs):
        nonlocal captured_coro
        captured_coro = coro
        # Close the coroutine to avoid RuntimeWarning
        coro.close()

    with (
        patch("app.services.providers.resolve_provider_for_model", return_value="my-provider"),
        patch("app.services.providers.get_llm_client", return_value=mock_client),
        patch("app.routers.api_v1_llm.safe_create_task", side_effect=capture_safe_create_task) as mock_sct,
        patch("app.services.providers.record_usage") as mock_tpm,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/llm/completions", json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hi"}],
            }, headers=HEADERS)

    assert resp.status_code == 200

    # Verify safe_create_task was called (usage trace recording)
    mock_sct.assert_called_once()

    # Verify TPM usage was recorded for rate limiting
    mock_tpm.assert_called_once_with("my-provider", 15)
