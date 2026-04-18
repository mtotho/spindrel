"""Integration tests for api_v1_admin/docker_stacks.py.

Routes under test:
- GET    /docker-stacks           — list with filters (bot_id, channel_id, status)
- GET    /docker-stacks/{id}      — get single, 404 on missing
- DELETE /docker-stacks/{id}      — destroy: 403 if source=="integration", 204 on success
- POST   /docker-stacks/{id}/start  — delegates to stack_service.start
- POST   /docker-stacks/{id}/stop   — delegates to stack_service.stop
- GET    /docker-stacks/{id}/status — delegates to stack_service.get_status
- GET    /docker-stacks/{id}/logs   — delegates to stack_service.get_logs

All stack_service I/O (Docker daemon) is patched — it is a true external system (E.1).

CRITICAL RULE pinned:
  destroy_docker_stack returns 403 (not 404 or 500) when source=="integration".
  Callers must not call DELETE on integration-managed stacks.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.factories import build_docker_stack
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio

_START = "app.services.docker_stacks.stack_service.start"
_STOP = "app.services.docker_stacks.stack_service.stop"
_DESTROY = "app.services.docker_stacks.stack_service.destroy"
_GET_STATUS = "app.services.docker_stacks.stack_service.get_status"
_GET_LOGS = "app.services.docker_stacks.stack_service.get_logs"


# ---------------------------------------------------------------------------
# GET /docker-stacks — list with filters
# ---------------------------------------------------------------------------

class TestListDockerStacks:
    async def test_when_stacks_exist_then_all_returned(self, client, db_session):
        s1 = build_docker_stack(created_by_bot="bot-a", status="running")
        s2 = build_docker_stack(created_by_bot="bot-b", status="stopped")
        db_session.add(s1)
        db_session.add(s2)
        await db_session.commit()

        resp = await client.get("/api/v1/admin/docker-stacks", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        ids = {r["id"] for r in resp.json()}
        assert str(s1.id) in ids
        assert str(s2.id) in ids

    async def test_when_filtered_by_bot_id_then_only_matching_returned(self, client, db_session):
        target = build_docker_stack(created_by_bot="bot-alpha")
        other = build_docker_stack(created_by_bot="bot-beta")
        db_session.add(target)
        db_session.add(other)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/admin/docker-stacks?bot_id=bot-alpha", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        ids = {r["id"] for r in resp.json()}
        assert str(target.id) in ids
        assert str(other.id) not in ids

    async def test_when_filtered_by_status_then_only_matching_returned(self, client, db_session):
        running = build_docker_stack(status="running")
        stopped = build_docker_stack(status="stopped")
        db_session.add(running)
        db_session.add(stopped)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/admin/docker-stacks?status=running", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        ids = {r["id"] for r in resp.json()}
        assert str(running.id) in ids
        assert str(stopped.id) not in ids


# ---------------------------------------------------------------------------
# GET /docker-stacks/{id} — get single
# ---------------------------------------------------------------------------

class TestGetDockerStack:
    async def test_when_exists_then_returned(self, client, db_session):
        row = build_docker_stack(name="my-nginx-stack")
        db_session.add(row)
        await db_session.commit()

        resp = await client.get(f"/api/v1/admin/docker-stacks/{row.id}", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["name"] == "my-nginx-stack"

    async def test_when_missing_then_404(self, client):
        resp = await client.get(
            f"/api/v1/admin/docker-stacks/{uuid.uuid4()}", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /docker-stacks/{id} — destroy
# ---------------------------------------------------------------------------

class TestDestroyDockerStack:
    async def test_when_source_is_integration_then_403(self, client, db_session):
        """Integration stacks are managed by code — admin cannot destroy them."""
        row = build_docker_stack(source="integration")
        db_session.add(row)
        await db_session.commit()

        with patch(_DESTROY, AsyncMock()):
            resp = await client.delete(
                f"/api/v1/admin/docker-stacks/{row.id}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 403
        assert "Integration" in resp.json()["detail"]

    async def test_when_source_is_bot_then_204(self, client, db_session):
        row = build_docker_stack(source="bot")
        db_session.add(row)
        await db_session.commit()

        with patch(_DESTROY, AsyncMock()):
            resp = await client.delete(
                f"/api/v1/admin/docker-stacks/{row.id}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 204

    async def test_when_missing_then_404(self, client):
        with patch(_DESTROY, AsyncMock()):
            resp = await client.delete(
                f"/api/v1/admin/docker-stacks/{uuid.uuid4()}", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /docker-stacks/{id}/start
# ---------------------------------------------------------------------------

class TestStartDockerStack:
    async def test_when_started_then_returns_updated_stack(self, client, db_session):
        row = build_docker_stack(status="stopped")
        db_session.add(row)
        await db_session.commit()

        started_row = build_docker_stack(id=row.id, status="running")
        with patch(_START, AsyncMock(return_value=started_row)):
            resp = await client.post(
                f"/api/v1/admin/docker-stacks/{row.id}/start", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    async def test_when_missing_then_404(self, client):
        with patch(_START, AsyncMock()):
            resp = await client.post(
                f"/api/v1/admin/docker-stacks/{uuid.uuid4()}/start", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /docker-stacks/{id}/stop
# ---------------------------------------------------------------------------

class TestStopDockerStack:
    async def test_when_stopped_then_returns_updated_stack(self, client, db_session):
        row = build_docker_stack(status="running")
        db_session.add(row)
        await db_session.commit()

        stopped_row = build_docker_stack(id=row.id, status="stopped")
        with patch(_STOP, AsyncMock(return_value=stopped_row)):
            resp = await client.post(
                f"/api/v1/admin/docker-stacks/{row.id}/stop", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"


# ---------------------------------------------------------------------------
# GET /docker-stacks/{id}/status
# ---------------------------------------------------------------------------

class TestGetDockerStackStatus:
    async def test_when_services_running_then_status_list_returned(self, client, db_session):
        row = build_docker_stack(status="running")
        db_session.add(row)
        await db_session.commit()

        svc = MagicMock()
        svc.name = "app"
        svc.state = "running"
        svc.health = "healthy"
        svc.ports = []

        with patch(_GET_STATUS, AsyncMock(return_value=[svc])):
            resp = await client.get(
                f"/api/v1/admin/docker-stacks/{row.id}/status", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()[0]["name"] == "app"
        assert resp.json()[0]["state"] == "running"


# ---------------------------------------------------------------------------
# GET /docker-stacks/{id}/logs
# ---------------------------------------------------------------------------

class TestGetDockerStackLogs:
    async def test_when_logs_available_then_returned(self, client, db_session):
        row = build_docker_stack(status="running")
        db_session.add(row)
        await db_session.commit()

        with patch(_GET_LOGS, AsyncMock(return_value="INFO started\nINFO ready")):
            resp = await client.get(
                f"/api/v1/admin/docker-stacks/{row.id}/logs", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert "INFO started" in resp.json()["logs"]
