"""Integration tests for api_v1_admin/operations.py.

Routes under test:
- GET  /operations              — list active background operations
- POST /operations/pull         — git pull (subprocess)
- POST /operations/restart      — confirm guard + git pull + systemctl restart
- GET  /operations/backup/config — reads server_settings (real DB, falls to defaults)
- PUT  /operations/backup/config — pg_insert; only 400 (no-fields) tested with SQLite
- GET  /operations/backup/history — lists local backup files; non-existent dir tested
- POST /operations/backup       — fires background task; task creation is swallowed

asyncio.create_subprocess_exec is patched globally; the test controls stdout/stderr
and returncode. create_task is swallowed to avoid uncompleted coroutine warnings.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


def _make_proc(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _swallow_task(coro) -> MagicMock:
    """Close the coroutine (suppress 'never awaited' warning) and return a fake Task."""
    coro.close()
    return MagicMock()


# ---------------------------------------------------------------------------
# GET /operations
# ---------------------------------------------------------------------------

class TestListOperations:
    async def test_when_no_active_ops_then_empty_list(self, client):
        with patch("app.services.progress.list_operations", return_value=[]):
            resp = await client.get("/api/v1/admin/operations", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["operations"] == []

    async def test_when_ops_exist_then_returned(self, client):
        fake_op = {"id": "op-1", "type": "backup", "status": "running", "label": "Running backup"}
        with patch("app.services.progress.list_operations", return_value=[fake_op]):
            resp = await client.get("/api/v1/admin/operations", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["operations"][0]["type"] == "backup"


# ---------------------------------------------------------------------------
# POST /operations/pull
# ---------------------------------------------------------------------------

class TestGitPull:
    async def test_when_pull_succeeds_then_exit_code_0(self, client):
        fetch_proc = _make_proc(returncode=0, stdout=b"")
        tag_proc = _make_proc(returncode=0, stdout=b"v9.9.9\nv1.0.0\n")
        checkout_proc = _make_proc(returncode=0, stdout=b"HEAD is now at release")
        create_subprocess = AsyncMock(side_effect=[fetch_proc, tag_proc, checkout_proc])

        with patch("asyncio.create_subprocess_exec", create_subprocess):
            resp = await client.post("/api/v1/admin/operations/pull", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["exit_code"] == 0
        assert "HEAD is now at release" in body["stdout"]
        assert create_subprocess.call_args_list[0].args[:6] == (
            "git",
            "-C",
            str(create_subprocess.call_args_list[0].args[2]),
            "fetch",
            "origin",
            "--tags",
        )
        assert create_subprocess.call_args_list[2].args[-2:] == ("--detach", "refs/tags/v9.9.9")

    async def test_when_development_channel_then_rebases_development(self, client):
        fetch_proc = _make_proc(returncode=0)
        switch_proc = _make_proc(returncode=0)
        pull_proc = _make_proc(returncode=0, stdout=b"Already up to date.")
        create_subprocess = AsyncMock(side_effect=[fetch_proc, switch_proc, pull_proc])

        with patch("asyncio.create_subprocess_exec", create_subprocess):
            resp = await client.post("/api/v1/admin/operations/pull?channel=development", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["exit_code"] == 0
        assert create_subprocess.call_args_list[0].args[-3:] == ("fetch", "origin", "development")
        assert create_subprocess.call_args_list[1].args[-2:] == ("switch", "development")
        assert create_subprocess.call_args_list[2].args[-4:] == (
            "pull",
            "--rebase",
            "origin",
            "development",
        )

    async def test_when_pull_fails_then_nonzero_exit_code_returned(self, client):
        proc = _make_proc(returncode=1, stdout=b"", stderr=b"fatal: not a git repo")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            resp = await client.post("/api/v1/admin/operations/pull", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["exit_code"] == 1
        assert "fatal" in body["stderr"]


# ---------------------------------------------------------------------------
# POST /operations/restart
# ---------------------------------------------------------------------------

class TestRestartServer:
    async def test_when_confirm_false_then_400(self, client):
        resp = await client.post(
            "/api/v1/admin/operations/restart",
            json={"confirm": False},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 400
        assert "confirm" in resp.json()["detail"].lower()

    async def test_when_confirm_missing_then_400(self, client):
        resp = await client.post(
            "/api/v1/admin/operations/restart",
            json={},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 400

    async def test_when_confirm_true_then_two_subprocesses_called(self, client):
        fetch_proc = _make_proc(returncode=0)
        tag_proc = _make_proc(returncode=0, stdout=b"v9.9.9\n")
        checkout_proc = _make_proc(returncode=0, stdout=b"HEAD is now at release")
        restart_proc = _make_proc(returncode=0)
        create_subprocess = AsyncMock(side_effect=[fetch_proc, tag_proc, checkout_proc, restart_proc])

        with patch("asyncio.create_subprocess_exec", create_subprocess):
            resp = await client.post(
                "/api/v1/admin/operations/restart",
                json={"confirm": True},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "pull" in body
        assert "restart" in body
        assert body["pull"]["exit_code"] == 0
        assert create_subprocess.call_args_list[2].args[-2:] == ("--detach", "refs/tags/v9.9.9")


# ---------------------------------------------------------------------------
# GET /operations/backup/config — reads from DB, falls back to defaults
# ---------------------------------------------------------------------------

class TestGetBackupConfig:
    async def test_when_no_db_overrides_then_defaults_returned(self, client):
        resp = await client.get("/api/v1/admin/operations/backup/config", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["local_keep"] == 7
        assert body["aws_region"] == "us-east-1"
        assert body["backup_dir"] == "./backups"


# ---------------------------------------------------------------------------
# PUT /operations/backup/config — pg_insert; only validation path is safe with SQLite
# ---------------------------------------------------------------------------

class TestUpdateBackupConfig:
    async def test_when_no_fields_then_400(self, client):
        resp = await client.put(
            "/api/v1/admin/operations/backup/config",
            json={},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 400
        assert "No fields" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /operations/backup/history — non-existent dir returns empty list
# ---------------------------------------------------------------------------

class TestBackupHistory:
    async def test_when_backup_dir_missing_then_empty_files_list(self, client):
        # Default backup_dir is ./backups (relative) — won't exist in test env.
        resp = await client.get("/api/v1/admin/operations/backup/history", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["files"] == []
        assert "backup_dir" in body


# ---------------------------------------------------------------------------
# POST /operations/backup — triggers background task
# ---------------------------------------------------------------------------

class TestTriggerBackup:
    async def test_when_script_missing_then_404(self, client):
        mock_script = MagicMock()
        mock_script.exists.return_value = False

        with patch("app.routers.api_v1_admin.operations._BACKUP_SCRIPT", mock_script):
            resp = await client.post("/api/v1/admin/operations/backup", headers=AUTH_HEADERS)

        assert resp.status_code == 404

    async def test_when_script_exists_then_op_started(self, client):
        mock_script = MagicMock()
        mock_script.exists.return_value = True

        with (
            patch("app.routers.api_v1_admin.operations._BACKUP_SCRIPT", mock_script),
            patch("asyncio.create_task", side_effect=_swallow_task),
        ):
            resp = await client.post("/api/v1/admin/operations/backup", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "started"
        assert "operation_id" in body
