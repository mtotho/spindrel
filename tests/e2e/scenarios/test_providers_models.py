"""Provider & model endpoint tests — deterministic, no LLM dependency.

All tests are read-only against existing provider/model data.
No providers are created, modified, or deleted.
"""

from __future__ import annotations

import pytest

from ..harness.client import E2EClient


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_providers(client: E2EClient) -> None:
    """GET /providers returns list with expected shape."""
    resp = await client.get("/api/v1/admin/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    providers = data["providers"]
    assert isinstance(providers, list)
    if providers:
        p = providers[0]
        assert "id" in p
        assert "provider_type" in p
        assert "display_name" in p


@pytest.mark.asyncio
async def test_get_provider(client: E2EClient) -> None:
    """GET /providers/{id} returns full provider detail."""
    # First get the list to find a valid ID
    resp = await client.get("/api/v1/admin/providers")
    providers = resp.json()["providers"]
    if not providers:
        pytest.skip("No providers configured")

    provider_id = providers[0]["id"]
    resp = await client.get(f"/api/v1/admin/providers/{provider_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == provider_id
    assert "provider_type" in data
    assert "display_name" in data
    assert "is_enabled" in data


@pytest.mark.asyncio
async def test_get_unknown_provider_404(client: E2EClient) -> None:
    """GET /providers/nonexistent returns 404."""
    resp = await client.get("/api/v1/admin/providers/e2e-nonexistent-provider")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_provider_models(client: E2EClient) -> None:
    """GET /providers/{id}/models returns model list."""
    resp = await client.get("/api/v1/admin/providers")
    providers = resp.json()["providers"]
    if not providers:
        pytest.skip("No providers configured")

    provider_id = providers[0]["id"]
    resp = await client.get(f"/api/v1/admin/providers/{provider_id}/models")
    assert resp.status_code == 200
    models = resp.json()
    assert isinstance(models, list)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_models_grouped(client: E2EClient) -> None:
    """GET /models returns models grouped by provider."""
    resp = await client.get("/api/v1/admin/models")
    assert resp.status_code == 200
    groups = resp.json()
    assert isinstance(groups, list)
    if groups:
        g = groups[0]
        assert "provider_id" in g
        assert "models" in g


@pytest.mark.asyncio
async def test_embedding_models(client: E2EClient) -> None:
    """GET /embedding-models returns embedding model list."""
    resp = await client.get("/api/v1/admin/embedding-models")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_completions(client: E2EClient) -> None:
    """GET /completions returns @-tag completion list."""
    resp = await client.get("/api/v1/admin/completions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        assert "value" in item
        assert "label" in item


@pytest.mark.asyncio
async def test_provider_capabilities(client: E2EClient) -> None:
    """GET /providers/{id}/capabilities returns provider capability info."""
    resp = await client.get("/api/v1/admin/providers")
    providers = resp.json()["providers"]
    if not providers:
        pytest.skip("No providers configured")

    provider_id = providers[0]["id"]
    resp = await client.get(f"/api/v1/admin/providers/{provider_id}/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
