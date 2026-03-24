"""Integration tests for /api/v1/workspaces endpoints."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest

from app.db.models import SharedWorkspace, SharedWorkspaceBot
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_workspace(client, **overrides) -> dict:
    payload = {
        "name": f"ws-{uuid.uuid4().hex[:8]}",
        "image": "agent-workspace:latest",
        **overrides,
    }
    resp = await client.post("/api/v1/workspaces", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v1/workspaces
# ---------------------------------------------------------------------------

class TestCreateWorkspace:
    async def test_create_workspace(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            resp = await client.post(
                "/api/v1/workspaces",
                json={"name": "test-workspace", "image": "python:3.12-slim"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "test-workspace"
        assert body["image"] == "python:3.12-slim"
        assert body["status"] == "stopped"
        assert body["network"] == "none"
        assert body["read_only_root"] is False
        assert body["bots"] == []
        uuid.UUID(body["id"])
        mock_svc.ensure_host_dirs.assert_called_once_with(body["id"])

    async def test_create_workspace_defaults(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            body = await _create_workspace(client)
        assert body["image"] == "agent-workspace:latest"
        assert body["network"] == "none"
        assert body["env"] == {}
        assert body["ports"] == []
        assert body["mounts"] == []
        assert body["cpus"] is None
        assert body["memory_limit"] is None

    async def test_create_workspace_with_description(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            body = await _create_workspace(client, description="My shared env")
        assert body["description"] == "My shared env"

    async def test_create_workspace_with_env(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            body = await _create_workspace(client, env={"FOO": "bar", "BAZ": "qux"})
        assert body["env"] == {"FOO": "bar", "BAZ": "qux"}

    async def test_create_workspace_with_resources(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            body = await _create_workspace(
                client, cpus=2.0, memory_limit="4g", read_only_root=True,
            )
        assert body["cpus"] == 2.0
        assert body["memory_limit"] == "4g"
        assert body["read_only_root"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/workspaces
# ---------------------------------------------------------------------------

class TestListWorkspaces:
    async def test_list_empty(self, client):
        resp = await client.get("/api/v1/workspaces", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 0

    async def test_list_with_data(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            await _create_workspace(client, name="ws-a")
            await _create_workspace(client, name="ws-b")
        resp = await client.get("/api/v1/workspaces", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        names = [w["name"] for w in resp.json()]
        assert "ws-a" in names
        assert "ws-b" in names


# ---------------------------------------------------------------------------
# GET /api/v1/workspaces/{id}
# ---------------------------------------------------------------------------

class TestGetWorkspace:
    async def test_get_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        resp = await client.get(f"/api/v1/workspaces/{ws_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == ws_id
        assert resp.json()["name"] == created["name"]

    async def test_get_workspace_not_found(self, client):
        resp = await client.get(
            f"/api/v1/workspaces/{uuid.uuid4()}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/v1/workspaces/{id}
# ---------------------------------------------------------------------------

class TestUpdateWorkspace:
    async def test_update_name(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        resp = await client.put(
            f"/api/v1/workspaces/{ws_id}",
            json={"name": "renamed-workspace"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed-workspace"

    async def test_update_description(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        resp = await client.put(
            f"/api/v1/workspaces/{ws_id}",
            json={"description": "Updated description"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated description"

    async def test_update_image(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        resp = await client.put(
            f"/api/v1/workspaces/{ws_id}",
            json={"image": "ubuntu:24.04"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["image"] == "ubuntu:24.04"

    async def test_update_resources(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        resp = await client.put(
            f"/api/v1/workspaces/{ws_id}",
            json={"cpus": 4.0, "memory_limit": "8g", "read_only_root": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cpus"] == 4.0
        assert body["memory_limit"] == "8g"
        assert body["read_only_root"] is True

    async def test_update_not_found(self, client):
        resp = await client.put(
            f"/api/v1/workspaces/{uuid.uuid4()}",
            json={"name": "nope"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/workspaces/{id}
# ---------------------------------------------------------------------------

class TestDeleteWorkspace:
    async def test_delete_workspace(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]

        with (
            patch("app.routers.api_v1_workspaces.shared_workspace_service"),
            patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock),
        ):
            resp = await client.delete(
                f"/api/v1/workspaces/{ws_id}", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 204

        # Verify deleted
        resp = await client.get(
            f"/api/v1/workspaces/{ws_id}", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_delete_not_found(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            resp = await client.delete(
                f"/api/v1/workspaces/{uuid.uuid4()}", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Container controls — start/stop/recreate/pull/status/logs
# ---------------------------------------------------------------------------

class TestContainerControls:
    async def test_start_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            created = await _create_workspace(client)
            ws_id = created["id"]
            mock_svc.ensure_container = AsyncMock()
            resp = await client.post(
                f"/api/v1/workspaces/{ws_id}/start", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        mock_svc.ensure_container.assert_awaited_once()

    async def test_start_not_found(self, client):
        resp = await client.post(
            f"/api/v1/workspaces/{uuid.uuid4()}/start", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_stop_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            created = await _create_workspace(client)
            ws_id = created["id"]
            mock_svc.stop = AsyncMock()
            resp = await client.post(
                f"/api/v1/workspaces/{ws_id}/stop", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        mock_svc.stop.assert_awaited_once()

    async def test_recreate_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            created = await _create_workspace(client)
            ws_id = created["id"]
            mock_svc.recreate = AsyncMock()
            resp = await client.post(
                f"/api/v1/workspaces/{ws_id}/recreate", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        mock_svc.recreate.assert_awaited_once()

    async def test_pull_image(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            created = await _create_workspace(client)
            ws_id = created["id"]
            mock_svc.pull_image = AsyncMock(return_value=(True, "Pulled OK"))
            resp = await client.post(
                f"/api/v1/workspaces/{ws_id}/pull", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["output"] == "Pulled OK"

    async def test_status(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            created = await _create_workspace(client)
            ws_id = created["id"]
            mock_svc.inspect_status = AsyncMock(return_value="running")
            resp = await client.get(
                f"/api/v1/workspaces/{ws_id}/status", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    async def test_logs(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            created = await _create_workspace(client)
            ws_id = created["id"]
            mock_svc.get_logs = AsyncMock(return_value="line 1\nline 2")
            resp = await client.get(
                f"/api/v1/workspaces/{ws_id}/logs", headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert "line 1" in resp.json()["logs"]


# ---------------------------------------------------------------------------
# Bot management — add/update/remove
# ---------------------------------------------------------------------------

class TestBotManagement:
    async def test_add_bot(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
                created = await _create_workspace(client)
                ws_id = created["id"]
                resp = await client.post(
                    f"/api/v1/workspaces/{ws_id}/bots",
                    json={"bot_id": "test-bot", "role": "member"},
                    headers=AUTH_HEADERS,
                )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["bots"]) == 1
        assert body["bots"][0]["bot_id"] == "test-bot"
        assert body["bots"][0]["role"] == "member"

    async def test_add_bot_as_orchestrator(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
                created = await _create_workspace(client)
                ws_id = created["id"]
                resp = await client.post(
                    f"/api/v1/workspaces/{ws_id}/bots",
                    json={"bot_id": "test-bot", "role": "orchestrator"},
                    headers=AUTH_HEADERS,
                )
        assert resp.status_code == 201
        assert resp.json()["bots"][0]["role"] == "orchestrator"

    async def test_add_bot_workspace_not_found(self, client):
        resp = await client.post(
            f"/api/v1/workspaces/{uuid.uuid4()}/bots",
            json={"bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_update_bot_role(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
                created = await _create_workspace(client)
                ws_id = created["id"]
                await client.post(
                    f"/api/v1/workspaces/{ws_id}/bots",
                    json={"bot_id": "test-bot", "role": "member"},
                    headers=AUTH_HEADERS,
                )
                resp = await client.put(
                    f"/api/v1/workspaces/{ws_id}/bots/test-bot",
                    json={"role": "orchestrator"},
                    headers=AUTH_HEADERS,
                )
        assert resp.status_code == 200
        assert resp.json()["role"] == "orchestrator"

    async def test_update_bot_not_in_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/workspaces/{ws_id}/bots/nonexistent",
                json={"role": "orchestrator"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    async def test_remove_bot(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
                created = await _create_workspace(client)
                ws_id = created["id"]
                await client.post(
                    f"/api/v1/workspaces/{ws_id}/bots",
                    json={"bot_id": "test-bot"},
                    headers=AUTH_HEADERS,
                )
                resp = await client.delete(
                    f"/api/v1/workspaces/{ws_id}/bots/test-bot",
                    headers=AUTH_HEADERS,
                )
        assert resp.status_code == 204

        # Verify bot is removed
        resp = await client.get(
            f"/api/v1/workspaces/{ws_id}", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert len(resp.json()["bots"]) == 0

    async def test_remove_bot_not_in_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.delete(
                f"/api/v1/workspaces/{ws_id}/bots/nonexistent",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# File browser
# ---------------------------------------------------------------------------

class TestFileBrowser:
    async def test_list_files(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service") as mock_svc:
            created = await _create_workspace(client)
            ws_id = created["id"]
            mock_svc.list_files.return_value = [
                {"name": "bots", "is_dir": True, "size": None, "path": "/bots"},
                {"name": "common", "is_dir": True, "size": None, "path": "/common"},
                {"name": "readme.txt", "is_dir": False, "size": 42, "path": "/readme.txt"},
            ]
            resp = await client.get(
                f"/api/v1/workspaces/{ws_id}/files",
                params={"path": "/"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["path"] == "/"
        assert len(body["entries"]) == 3
        names = [e["name"] for e in body["entries"]]
        assert "bots" in names
        assert "readme.txt" in names

    async def test_list_files_not_found(self, client):
        resp = await client.get(
            f"/api/v1/workspaces/{uuid.uuid4()}/files",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404
