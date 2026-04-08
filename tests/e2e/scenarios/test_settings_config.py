"""Settings & config endpoint tests — deterministic, no LLM dependency.

Verifies that settings, status, and config endpoints return correct shapes.
All tests are read-only (GET) except one that tests DELETE on a nonexistent key.
"""

from __future__ import annotations

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_status_shape(client: E2EClient) -> None:
    """GET /status returns paused flag and pause_behavior."""
    resp = await client.get("/api/v1/admin/status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["paused"], bool)
    assert "pause_behavior" in data


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_list_shape(client: E2EClient) -> None:
    """GET /settings returns grouped settings."""
    resp = await client.get("/api/v1/admin/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "groups" in data
    assert isinstance(data["groups"], list)


@pytest.mark.asyncio
async def test_chat_history_deviations(client: E2EClient) -> None:
    """GET /settings/chat-history-deviations returns channels list."""
    resp = await client.get("/api/v1/admin/settings/chat-history-deviations")
    assert resp.status_code == 200
    data = resp.json()
    assert "channels" in data
    assert isinstance(data["channels"], list)


@pytest.mark.asyncio
async def test_memory_scheme_defaults(client: E2EClient) -> None:
    """GET /settings/memory-scheme-defaults returns prompt templates."""
    resp = await client.get("/api/v1/admin/settings/memory-scheme-defaults")
    assert resp.status_code == 200
    data = resp.json()
    assert "prompt" in data
    assert "flush_prompt" in data
    assert isinstance(data["prompt"], str)
    assert len(data["prompt"]) > 0


@pytest.mark.asyncio
async def test_settings_unknown_key_delete_422(client: E2EClient) -> None:
    """DELETE /settings/{key} with unknown key returns 422."""
    resp = await client.delete("/api/v1/admin/settings/e2e-nonexistent-key-12345")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Global model config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_fallback_models(client: E2EClient) -> None:
    """GET /global-fallback-models returns models list."""
    resp = await client.get("/api/v1/admin/global-fallback-models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert isinstance(data["models"], list)


@pytest.mark.asyncio
async def test_global_model_tiers(client: E2EClient) -> None:
    """GET /global-model-tiers returns tiers dict."""
    resp = await client.get("/api/v1/admin/global-model-tiers")
    assert resp.status_code == 200
    data = resp.json()
    assert "tiers" in data
    assert isinstance(data["tiers"], dict)


# ---------------------------------------------------------------------------
# Health (extended)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_extended_shape(client: E2EClient) -> None:
    """GET /health returns extended health info."""
    data = await client.health()
    assert "healthy" in data
    assert isinstance(data["healthy"], bool)
    assert "database" in data
    assert "uptime_seconds" in data
    assert isinstance(data["uptime_seconds"], (int, float))
    assert "bot_count" in data
