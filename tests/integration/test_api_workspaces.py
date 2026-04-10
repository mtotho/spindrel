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


async def _add_bot_to_workspace(
    db_session,
    ws_id: str,
    bot_id: str,
    *,
    role: str = "member",
    cwd_override: str | None = None,
    write_access: list[str] | None = None,
) -> None:
    """Insert a SharedWorkspaceBot row directly.

    The POST endpoint is retired (single-workspace mode); production membership
    is owned by the bootstrap loop. Tests that need a workspace-bot row should
    create it directly, the same way `ensure_all_bots_enrolled` does at startup.
    """
    swb = SharedWorkspaceBot(
        workspace_id=uuid.UUID(ws_id),
        bot_id=bot_id,
        role=role,
        cwd_override=cwd_override,
        write_access=write_access or [],
    )
    db_session.add(swb)
    await db_session.commit()


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

    async def test_list_with_data(self, client, db_session):
        # Insert workspaces directly into DB (POST guard blocks creating >1)
        now = datetime.now(timezone.utc)
        for name in ("ws-a", "ws-b"):
            ws = SharedWorkspace(
                name=name, image="img:latest", status="stopped",
                created_at=now, updated_at=now,
            )
            db_session.add(ws)
        await db_session.commit()

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
    async def test_delete_workspace_blocked(self, client, db_session):
        """DELETE always returns 400 in single-workspace mode."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]

        resp = await client.delete(
            f"/api/v1/workspaces/{ws_id}", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400

    async def test_delete_not_found_also_blocked(self, client):
        """DELETE returns 400 regardless of whether workspace exists."""
        resp = await client.delete(
            f"/api/v1/workspaces/{uuid.uuid4()}", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400


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
# Bot management — POST/DELETE retired (single-workspace mode), PUT still works
# ---------------------------------------------------------------------------

class TestBotManagement:
    async def test_add_bot_returns_410(self, client, db_session):
        """Single-workspace mode: bot membership is owned by the bootstrap loop,
        the POST endpoint is retired."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/bots",
            json={"bot_id": "test-bot", "role": "member"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 410
        assert "single-workspace" in resp.json()["detail"].lower()

    async def test_remove_bot_returns_410(self, client, db_session):
        """DELETE endpoint is retired for the same reason as POST."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        await _add_bot_to_workspace(db_session, ws_id, "test-bot")
        resp = await client.delete(
            f"/api/v1/workspaces/{ws_id}/bots/test-bot",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 410
        # Verify the membership row is still there — the 410 must not have
        # been wired to a side-effecting body.
        resp = await client.get(
            f"/api/v1/workspaces/{ws_id}", headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert len(resp.json()["bots"]) == 1

    async def test_update_bot_role(self, client, db_session):
        """PUT continues to work for updating role/cwd_override/write_access on
        existing memberships — only join/leave is retired, not config edits."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        await _add_bot_to_workspace(db_session, ws_id, "test-bot", role="member")
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
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


# ---------------------------------------------------------------------------
# Indexing config on workspace CRUD
# ---------------------------------------------------------------------------

class TestWorkspaceIndexingConfig:
    async def test_create_workspace_no_indexing_config(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            body = await _create_workspace(client)
        assert body.get("indexing_config") is None

    async def test_update_workspace_with_indexing_config(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        cfg = {"patterns": ["**/*.py", "**/*.ts"], "similarity_threshold": 0.25, "top_k": 12}
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/workspaces/{ws_id}",
                json={"indexing_config": cfg},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["indexing_config"]["patterns"] == ["**/*.py", "**/*.ts"]
        assert body["indexing_config"]["similarity_threshold"] == 0.25
        assert body["indexing_config"]["top_k"] == 12

    async def test_get_workspace_returns_indexing_config(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        # Set indexing config directly in DB
        ws = await db_session.get(SharedWorkspace, uuid.UUID(ws_id))
        ws.indexing_config = {"patterns": ["**/*.md"], "top_k": 5}
        await db_session.commit()

        resp = await client.get(f"/api/v1/workspaces/{ws_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["indexing_config"]["patterns"] == ["**/*.md"]
        assert body["indexing_config"]["top_k"] == 5


# ---------------------------------------------------------------------------
# GET /api/v1/workspaces/{id}/indexing
# ---------------------------------------------------------------------------

class TestGetWorkspaceIndexing:
    async def test_indexing_not_found(self, client):
        resp = await client.get(
            f"/api/v1/workspaces/{uuid.uuid4()}/indexing",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_indexing_returns_global_defaults(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        resp = await client.get(f"/api/v1/workspaces/{ws_id}/indexing", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert "global_defaults" in body
        assert body["global_defaults"]["patterns"] == ["**/*.py", "**/*.md", "**/*.yaml"]
        assert body["global_defaults"]["similarity_threshold"] == 0.30
        assert body["global_defaults"]["top_k"] == 8
        assert "supported_languages" in body
        assert "skip_extensions" in body
        assert "skip_directories" in body
        assert body["workspace_defaults"] is None  # no workspace config set
        assert body["bots"] == []  # no bots added

    async def test_indexing_with_workspace_defaults(self, client, db_session):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        ws = await db_session.get(SharedWorkspace, uuid.UUID(ws_id))
        ws.indexing_config = {"patterns": ["**/*.py"], "similarity_threshold": 0.20}
        await db_session.commit()

        resp = await client.get(f"/api/v1/workspaces/{ws_id}/indexing", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["workspace_defaults"]["patterns"] == ["**/*.py"]
        assert body["workspace_defaults"]["similarity_threshold"] == 0.20

    async def test_indexing_with_bots(self, client, db_session):
        """Bot list includes resolved indexing config when bots are added."""
        from app.agent.bots import BotConfig, WorkspaceConfig, WorkspaceIndexingConfig

        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        await _add_bot_to_workspace(db_session, ws_id, "test-bot", role="member")

        # Patch list_bots to return a bot with workspace config
        test_bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="test",
            workspace=WorkspaceConfig(
                enabled=True,
                indexing=WorkspaceIndexingConfig(
                    enabled=True,
                    patterns=["**/*.py"],
                    similarity_threshold=0.15,
                ),
            ),
            _workspace_raw={"indexing": {"patterns": ["**/*.py"], "similarity_threshold": 0.15}},
        )
        with patch("app.routers.api_v1_workspaces.list_bots", return_value=[test_bot]):
            resp = await client.get(f"/api/v1/workspaces/{ws_id}/indexing", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["bots"]) == 1
        bot_info = body["bots"][0]
        assert bot_info["bot_id"] == "test-bot"
        assert bot_info["indexing_enabled"] is True
        assert bot_info["explicit_overrides"]["patterns"] == ["**/*.py"]
        assert bot_info["resolved"]["patterns"] == ["**/*.py"]
        assert bot_info["resolved"]["similarity_threshold"] == 0.15


# ---------------------------------------------------------------------------
# PUT /api/v1/workspaces/{id}/bots/{bot_id}/indexing
# ---------------------------------------------------------------------------

class TestUpdateBotIndexing:
    async def _setup_workspace_with_bot(self, client, db_session):
        """Create workspace and add a bot directly via the DB, return ws_id."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        await _add_bot_to_workspace(db_session, ws_id, "test-bot", role="member")
        # Need a Bot row for the update to work
        from app.db.models import Bot as BotRow
        bot_row = BotRow(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="test",
            workspace={"enabled": True, "indexing": {"enabled": True}},
        )
        db_session.add(bot_row)
        await db_session.commit()
        return ws_id

    async def test_update_not_found_workspace(self, client):
        resp = await client.put(
            f"/api/v1/workspaces/{uuid.uuid4()}/bots/test-bot/indexing",
            json={"top_k": 15},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_update_bot_not_in_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        ws_id = created["id"]
        resp = await client.put(
            f"/api/v1/workspaces/{ws_id}/bots/nonexistent/indexing",
            json={"top_k": 15},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_update_sets_indexing_override(self, client, db_session):
        ws_id = await self._setup_workspace_with_bot(client, db_session)
        from app.agent.bots import BotConfig, WorkspaceConfig, WorkspaceIndexingConfig
        test_bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="test",
            workspace=WorkspaceConfig(
                enabled=True,
                indexing=WorkspaceIndexingConfig(
                    enabled=True,
                    patterns=["**/*.py"],
                    top_k=15,
                ),
            ),
            _workspace_raw={"enabled": True, "indexing": {"enabled": True, "patterns": ["**/*.py"], "top_k": 15}},
        )
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            with patch("app.routers.api_v1_workspaces.list_bots", return_value=[test_bot]):
                resp = await client.put(
                    f"/api/v1/workspaces/{ws_id}/bots/test-bot/indexing",
                    json={"patterns": ["**/*.py"], "top_k": 15},
                    headers=AUTH_HEADERS,
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["bot_id"] == "test-bot"
        assert body["explicit_overrides"]["patterns"] == ["**/*.py"]
        assert body["explicit_overrides"]["top_k"] == 15

    async def test_update_null_clears_override(self, client, db_session):
        ws_id = await self._setup_workspace_with_bot(client, db_session)
        # First set a top_k override
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            with patch("app.routers.api_v1_workspaces.list_bots", return_value=[]):
                await client.put(
                    f"/api/v1/workspaces/{ws_id}/bots/test-bot/indexing",
                    json={"top_k": 15},
                    headers=AUTH_HEADERS,
                )
        # Verify top_k was set on bot row
        from app.db.models import Bot as BotRow
        db_session.expire_all()
        bot_row = await db_session.get(BotRow, "test-bot")
        assert bot_row.workspace["indexing"]["top_k"] == 15

        # Now clear it
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            with patch("app.routers.api_v1_workspaces.list_bots", return_value=[]):
                resp = await client.put(
                    f"/api/v1/workspaces/{ws_id}/bots/test-bot/indexing",
                    json={"top_k": None},
                    headers=AUTH_HEADERS,
                )
        assert resp.status_code == 200
        db_session.expire_all()
        bot_row = await db_session.get(BotRow, "test-bot")
        assert "top_k" not in bot_row.workspace.get("indexing", {})


# ---------------------------------------------------------------------------
# GET /workspaces/{id}/bots/{bot_id}  +  PUT (system_prompt etc.)
# ---------------------------------------------------------------------------

class TestWorkspaceBotConfig:
    """Tests for reading and updating bot config via workspace endpoints."""

    async def _setup_workspace_with_bot(self, client, db_session):
        """Create workspace, add a bot row + workspace membership, return ws_id."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        await _add_bot_to_workspace(db_session, ws_id, "cfg-bot", role="member")
        from app.db.models import Bot as BotRow
        bot_row = BotRow(
            id="cfg-bot",
            name="Config Bot",
            model="test/model",
            system_prompt="Original prompt.",
            workspace={"enabled": True},
            skills=[{"id": "cooking", "mode": "on_demand"}],
            local_tools=["web_search"],
            persona=False,
        )
        db_session.add(bot_row)
        await db_session.commit()
        return ws_id

    # ── GET ────────────────────────────────────────────────────────

    async def test_get_bot_returns_config(self, client, db_session):
        ws_id = await self._setup_workspace_with_bot(client, db_session)
        from app.agent.bots import BotConfig, WorkspaceConfig, WorkspaceIndexingConfig
        mock_bot = BotConfig(
            id="cfg-bot", name="Config Bot", model="test/model",
            system_prompt="Original prompt.",
            workspace=WorkspaceConfig(enabled=True, indexing=WorkspaceIndexingConfig(enabled=True)),
        )
        with patch("app.routers.api_v1_workspaces.list_bots", return_value=[mock_bot]):
            resp = await client.get(
                f"/api/v1/workspaces/{ws_id}/bots/cfg-bot",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["bot_id"] == "cfg-bot"
        assert body["name"] == "Config Bot"
        assert body["model"] == "test/model"
        assert body["system_prompt"] == "Original prompt."
        assert body["role"] == "member"
        assert body["skills"] == [{"id": "cooking", "mode": "on_demand"}]
        assert body["local_tools"] == ["web_search"]
        assert body["persona"] is False
        assert body["indexing_enabled"] is True

    async def test_get_bot_not_in_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        resp = await client.get(
            f"/api/v1/workspaces/{created['id']}/bots/nonexistent",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    # ── PUT system_prompt ──────────────────────────────────────────

    async def test_update_system_prompt(self, client, db_session):
        ws_id = await self._setup_workspace_with_bot(client, db_session)
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/workspaces/{ws_id}/bots/cfg-bot",
                json={"system_prompt": "You are now a pastry chef."},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["system_prompt"] == "You are now a pastry chef."
        # Verify persisted to DB
        from app.db.models import Bot as BotRow
        db_session.expire_all()
        row = await db_session.get(BotRow, "cfg-bot")
        assert row.system_prompt == "You are now a pastry chef."

    async def test_update_model_and_name(self, client, db_session):
        ws_id = await self._setup_workspace_with_bot(client, db_session)
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/workspaces/{ws_id}/bots/cfg-bot",
                json={"name": "Chef Bot", "model": "openai/gpt-4o"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Chef Bot"
        assert body["model"] == "openai/gpt-4o"
        from app.db.models import Bot as BotRow
        db_session.expire_all()
        row = await db_session.get(BotRow, "cfg-bot")
        assert row.name == "Chef Bot"
        assert row.model == "openai/gpt-4o"

    async def test_update_skills(self, client, db_session):
        ws_id = await self._setup_workspace_with_bot(client, db_session)
        new_skills = [
            {"id": "cooking", "mode": "on_demand"},
            {"id": "nutrition", "mode": "on_demand"},
        ]
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/workspaces/{ws_id}/bots/cfg-bot",
                json={"skills": new_skills},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        from app.db.models import Bot as BotRow
        db_session.expire_all()
        row = await db_session.get(BotRow, "cfg-bot")
        assert len(row.skills) == 2
        assert row.skills[1]["id"] == "nutrition"

    async def test_update_only_role_no_bot_row_needed(self, client, db_session):
        """Updating only workspace membership fields doesn't touch bots table."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        await _add_bot_to_workspace(db_session, ws_id, "role-bot", role="member")
        # No BotRow created — should still work for role-only update
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/workspaces/{ws_id}/bots/role-bot",
                json={"role": "orchestrator"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["role"] == "orchestrator"

    async def test_update_prompt_bot_not_in_workspace(self, client):
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
        with patch("app.routers.api_v1_workspaces.reload_bots", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/workspaces/{created['id']}/bots/nonexistent",
                json={"system_prompt": "new prompt"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/workspaces/{workspace_id}/reindex
# ---------------------------------------------------------------------------

class TestReindexWorkspace:
    async def _setup_workspace_with_bot(self, client, db_session, *, memory_scheme=None, indexing_enabled=True, segments=None):
        """Create workspace + add a bot to it."""
        with patch("app.routers.api_v1_workspaces.shared_workspace_service"):
            created = await _create_workspace(client)
            ws_id = created["id"]
        await _add_bot_to_workspace(db_session, ws_id, "test-bot", role="member")
        return ws_id

    async def test_reindex_not_found(self, client):
        resp = await client.post(
            f"/api/v1/workspaces/{uuid.uuid4()}/reindex",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_reindex_memory_only_bot(self, client, db_session):
        """Bot with workspace-files memory + no segments → Phase 1 runs, Phase 2 skips."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig, WorkspaceConfig, WorkspaceIndexingConfig

        ws_id = await self._setup_workspace_with_bot(client, db_session)

        mock_bot = BotConfig(
            id="test-bot", name="Test", model="test/model",
            system_prompt="test",
            memory=MemoryConfig(), knowledge=KnowledgeConfig(),
            memory_scheme="workspace-files",
            workspace=WorkspaceConfig(enabled=True, indexing=WorkspaceIndexingConfig(enabled=True)),
            shared_workspace_id=ws_id,
            shared_workspace_role="member",
            _workspace_raw={},
        )
        mock_mem_stats = {"files": 3, "chunks": 12}

        with (
            patch("app.routers.api_v1_workspaces.list_bots", return_value=[mock_bot]),
            patch("app.services.memory_indexing.index_memory_for_bot", new_callable=AsyncMock, return_value=mock_mem_stats) as mock_mem,
            patch("app.agent.fs_indexer.cleanup_stale_roots", new_callable=AsyncMock, return_value=0),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/root"]),
            patch("app.services.workspace_indexing.resolve_indexing", return_value={
                "patterns": ["**/*.md"], "embedding_model": "text-embedding-3-small",
                "segments": None, "top_k": 5, "similarity_threshold": 0.3,
                "cooldown_seconds": 300, "watch": True,
            }),
        ):
            resp = await client.post(f"/api/v1/workspaces/{ws_id}/reindex", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        # Memory phase ran
        assert "test-bot" in body["results"]
        assert "memory" in body["results"]["test-bot"]
        # Phase 2 should NOT have run (no segments for shared ws bot)
        assert "indexing" not in body["results"]["test-bot"]

    async def test_reindex_with_segments(self, client, db_session):
        """Bot with segments configured → Phase 2 runs."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig, WorkspaceConfig, WorkspaceIndexingConfig

        ws_id = await self._setup_workspace_with_bot(client, db_session)

        mock_bot = BotConfig(
            id="test-bot", name="Test", model="test/model",
            system_prompt="test",
            memory=MemoryConfig(), knowledge=KnowledgeConfig(),
            memory_scheme="workspace-files",
            workspace=WorkspaceConfig(enabled=True, indexing=WorkspaceIndexingConfig(enabled=True)),
            shared_workspace_id=ws_id,
            shared_workspace_role="member",
            _workspace_raw={},
        )
        mock_index_stats = {"chunks_inserted": 10, "files_processed": 3}
        segments = [{"path_prefix": "common/", "embedding_model": None}]

        with (
            patch("app.routers.api_v1_workspaces.list_bots", return_value=[mock_bot]),
            patch("app.services.memory_indexing.index_memory_for_bot", new_callable=AsyncMock, return_value={"files": 2}),
            patch("app.agent.fs_indexer.cleanup_stale_roots", new_callable=AsyncMock, return_value=0),
            patch("app.agent.fs_indexer.index_directory", new_callable=AsyncMock, return_value=mock_index_stats) as mock_idx,
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/root"]),
            patch("app.services.workspace_indexing.resolve_indexing", return_value={
                "patterns": ["**/*.md"], "embedding_model": "text-embedding-3-small",
                "segments": segments, "top_k": 5, "similarity_threshold": 0.3,
                "cooldown_seconds": 300, "watch": True,
            }),
        ):
            resp = await client.post(f"/api/v1/workspaces/{ws_id}/reindex", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert "indexing" in body["results"]["test-bot"]
        mock_idx.assert_awaited_once()

    async def test_reindex_cleanup_stale_roots(self, client, db_session):
        """Phase 0: cleanup_stale_roots should be called."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig, WorkspaceConfig, WorkspaceIndexingConfig

        ws_id = await self._setup_workspace_with_bot(client, db_session)

        mock_bot = BotConfig(
            id="test-bot", name="Test", model="test/model",
            system_prompt="test",
            memory=MemoryConfig(), knowledge=KnowledgeConfig(),
            workspace=WorkspaceConfig(enabled=True, indexing=WorkspaceIndexingConfig(enabled=False)),
            shared_workspace_id=ws_id,
            _workspace_raw={},
        )

        with (
            patch("app.routers.api_v1_workspaces.list_bots", return_value=[mock_bot]),
            patch("app.agent.fs_indexer.cleanup_stale_roots", new_callable=AsyncMock, return_value=2) as mock_cleanup,
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/root"]),
        ):
            resp = await client.post(f"/api/v1/workspaces/{ws_id}/reindex", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        mock_cleanup.assert_awaited_once_with("test-bot", ["/ws/root"])
        body = resp.json()
        assert body["results"]["test-bot"]["stale_roots_cleaned"] == 2
