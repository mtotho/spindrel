"""Tests for bot sandbox status and recreate API endpoints."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS


@pytest.mark.asyncio
async def test_sandbox_status_no_container(client, db_session):
    """GET /bots/{bot_id}/sandbox returns exists=false when no container."""
    resp = await client.get("/api/v1/admin/bots/test-bot/sandbox", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is False
    assert data["status"] is None


@pytest.mark.asyncio
async def test_sandbox_status_with_container(client, db_session):
    """GET /bots/{bot_id}/sandbox returns container info when one exists."""
    from datetime import datetime, timezone
    from app.db.models import SandboxInstance, SandboxProfile

    # Create a sandbox profile + instance
    profile_id = uuid.uuid4()
    profile = SandboxProfile(
        id=profile_id,
        name="bot-local:test-bot",
        description="Test sandbox",
        image="python:3.12-slim",
        scope_mode="bot",
    )
    db_session.add(profile)

    now = datetime.now(timezone.utc)
    instance = SandboxInstance(
        id=uuid.uuid4(),
        profile_id=profile_id,
        scope_type="bot",
        scope_key="test-bot",
        container_id="abc123def456789012345678",
        container_name="agent-sbx-bot-test-bot",
        status="running",
        created_by_bot="test-bot",
        image_id="sha256:abcdef1234567890",
        created_at=now,
        last_used_at=now,
    )
    db_session.add(instance)
    await db_session.commit()

    resp = await client.get("/api/v1/admin/bots/test-bot/sandbox", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is True
    assert data["status"] == "running"
    assert data["container_name"] == "agent-sbx-bot-test-bot"
    assert data["container_id"] == "abc123def456"  # truncated to 12
    assert data["image_id"] == "sha256:abcdef123456"  # truncated to 19 chars


@pytest.mark.asyncio
async def test_sandbox_status_with_error(client, db_session):
    """GET /bots/{bot_id}/sandbox shows error_message when container is dead."""
    from app.db.models import SandboxInstance, SandboxProfile

    profile_id = uuid.uuid4()
    db_session.add(SandboxProfile(
        id=profile_id, name="bot-local:test-bot", description="", image="python:3.12-slim", scope_mode="bot",
    ))
    db_session.add(SandboxInstance(
        id=uuid.uuid4(), profile_id=profile_id, scope_type="bot", scope_key="test-bot",
        container_name="agent-sbx-bot-test-bot", status="dead", created_by_bot="test-bot",
        error_message="OOM killed",
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/admin/bots/test-bot/sandbox", headers=AUTH_HEADERS)
    data = resp.json()
    assert data["exists"] is True
    assert data["status"] == "dead"
    assert data["error_message"] == "OOM killed"


@pytest.mark.asyncio
async def test_sandbox_recreate(client, db_session):
    """POST /bots/{bot_id}/sandbox/recreate calls sandbox_service.recreate_bot_local."""
    mock_recreate = AsyncMock()
    with patch("app.services.sandbox.SandboxService.recreate_bot_local", mock_recreate):
        resp = await client.post("/api/v1/admin/bots/test-bot/sandbox/recreate", headers=AUTH_HEADERS)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_recreate.assert_awaited_once_with("test-bot")


@pytest.mark.asyncio
async def test_sandbox_recreate_error(client, db_session):
    """POST /bots/{bot_id}/sandbox/recreate returns 500 on failure."""
    mock_recreate = AsyncMock(side_effect=RuntimeError("Docker not running"))
    with patch("app.services.sandbox.SandboxService.recreate_bot_local", mock_recreate):
        resp = await client.post("/api/v1/admin/bots/test-bot/sandbox/recreate", headers=AUTH_HEADERS)

    assert resp.status_code == 500
    assert "Docker not running" in resp.json()["detail"]
