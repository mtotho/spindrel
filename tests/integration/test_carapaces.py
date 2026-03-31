"""Integration tests for carapace API endpoints."""
import pytest

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.mark.asyncio
async def test_carapace_crud(client):
    """Test create, list, get, update, delete lifecycle via admin endpoints."""
    # Create
    resp = await client.post(
        "/api/v1/admin/carapaces",
        json={
            "id": "test-qa",
            "name": "QA Expert",
            "description": "Full QA workflow",
            "skills": [{"id": "testing", "mode": "pinned"}],
            "local_tools": ["exec_command", "file"],
            "pinned_tools": ["exec_command"],
            "tags": ["testing"],
            "system_prompt_fragment": "Be thorough.",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "test-qa"
    assert data["name"] == "QA Expert"
    assert len(data["skills"]) == 1
    assert data["local_tools"] == ["exec_command", "file"]

    # List
    resp = await client.get("/api/v1/admin/carapaces", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    items = resp.json()
    assert any(c["id"] == "test-qa" for c in items)

    # Get
    resp = await client.get("/api/v1/admin/carapaces/test-qa", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["name"] == "QA Expert"

    # Update
    resp = await client.put(
        "/api/v1/admin/carapaces/test-qa",
        json={"name": "QA Expert v2", "tags": ["testing", "quality"]},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "QA Expert v2"
    assert resp.json()["tags"] == ["testing", "quality"]

    # Export
    resp = await client.post("/api/v1/admin/carapaces/test-qa/export", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert "test-qa" in resp.text

    # Delete
    resp = await client.delete("/api/v1/admin/carapaces/test-qa", headers=AUTH_HEADERS)
    assert resp.status_code == 200

    # Verify deleted
    resp = await client.get("/api/v1/admin/carapaces/test-qa", headers=AUTH_HEADERS)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_carapace_bot_facing_api(client):
    """Test bot-facing /api/v1/carapaces endpoints."""
    # Create via bot-facing API
    resp = await client.post(
        "/api/v1/carapaces",
        json={
            "id": "bot-created",
            "name": "Bot Created",
            "local_tools": ["web_search"],
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201

    # List
    resp = await client.get("/api/v1/carapaces", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert any(c["id"] == "bot-created" for c in resp.json())

    # Get
    resp = await client.get("/api/v1/carapaces/bot-created", headers=AUTH_HEADERS)
    assert resp.status_code == 200

    # Update
    resp = await client.put(
        "/api/v1/carapaces/bot-created",
        json={"name": "Bot Created v2"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Bot Created v2"

    # Cleanup
    resp = await client.delete("/api/v1/admin/carapaces/bot-created", headers=AUTH_HEADERS)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_carapace_rejected(client):
    resp = await client.post(
        "/api/v1/admin/carapaces",
        json={"id": "dup-test", "name": "Dup"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/admin/carapaces",
        json={"id": "dup-test", "name": "Dup Again"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 409

    # Cleanup
    await client.delete("/api/v1/admin/carapaces/dup-test", headers=AUTH_HEADERS)
