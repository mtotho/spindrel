"""Tests for security fixes: admin auth, path traversal, policy fail-closed, task_type validation."""
import json
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. verify_admin_auth rejects non-admin JWT users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_admin_auth_rejects_non_admin_jwt():
    """JWT user with is_admin=False must get 403 from verify_admin_auth."""
    from fastapi import HTTPException
    from app.dependencies import verify_admin_auth

    fake_user = type("User", (), {"id": uuid.uuid4(), "is_active": True, "is_admin": False})()
    fake_payload = {"sub": str(fake_user.id)}

    mock_db = AsyncMock()

    with (
        patch("app.services.auth.decode_access_token", return_value=fake_payload),
        patch("app.services.auth.get_user_by_id", new_callable=AsyncMock, return_value=fake_user),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_auth(authorization="Bearer fake-jwt", db=mock_db)
        assert exc_info.value.status_code == 403
        assert "Admin access denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_verify_admin_auth_allows_admin_jwt():
    """JWT user with is_admin=True must pass verify_admin_auth."""
    from app.dependencies import verify_admin_auth

    fake_user = type("User", (), {"id": uuid.uuid4(), "is_active": True, "is_admin": True})()
    fake_payload = {"sub": str(fake_user.id)}

    mock_db = AsyncMock()

    with (
        patch("app.services.auth.decode_access_token", return_value=fake_payload),
        patch("app.services.auth.get_user_by_id", new_callable=AsyncMock, return_value=fake_user),
    ):
        result = await verify_admin_auth(authorization="Bearer fake-jwt", db=mock_db)
        assert result is fake_user


# ---------------------------------------------------------------------------
# 2. write_workspace_file uses realpath (prevents symlink traversal)
# ---------------------------------------------------------------------------

def test_write_workspace_file_blocks_dotdot_traversal(tmp_path):
    """Path traversal with ../ must be rejected."""
    from app.services.channel_workspace import write_workspace_file

    ws_root = str(tmp_path / "workspace" / "channels" / "ch-1")
    os.makedirs(ws_root, exist_ok=True)

    with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_root):
        with pytest.raises(ValueError, match="Path escapes workspace root"):
            write_workspace_file("ch-1", None, "../../etc/passwd", "hacked")


def test_write_workspace_file_blocks_symlink_traversal(tmp_path):
    """Symlink pointing outside workspace must be caught by realpath."""
    from app.services.channel_workspace import write_workspace_file

    ws_root = str(tmp_path / "workspace" / "channels" / "ch-1")
    os.makedirs(ws_root, exist_ok=True)

    # Create a symlink inside ws_root that points outside
    outside_dir = str(tmp_path / "outside")
    os.makedirs(outside_dir, exist_ok=True)
    symlink_path = os.path.join(ws_root, "evil_link")
    os.symlink(outside_dir, symlink_path)

    with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_root):
        with pytest.raises(ValueError, match="Path escapes workspace root"):
            write_workspace_file("ch-1", None, "evil_link/pwned.txt", "hacked")


def test_write_workspace_file_allows_normal_paths(tmp_path):
    """Normal relative paths should work fine."""
    from app.services.channel_workspace import write_workspace_file

    ws_root = str(tmp_path / "workspace" / "channels" / "ch-1")
    os.makedirs(ws_root, exist_ok=True)

    with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_root):
        result = write_workspace_file("ch-1", None, "notes.md", "hello")
        assert result["path"] == "notes.md"
        assert os.path.isfile(os.path.join(ws_root, "notes.md"))


def test_write_workspace_file_allows_subdirs(tmp_path):
    """Subdirectory paths like data/file.md should work."""
    from app.services.channel_workspace import write_workspace_file

    ws_root = str(tmp_path / "workspace" / "channels" / "ch-1")
    os.makedirs(ws_root, exist_ok=True)

    with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=ws_root):
        result = write_workspace_file("ch-1", None, "data/report.md", "content")
        assert result["path"] == "data/report.md"
        assert os.path.isfile(os.path.join(ws_root, "data", "report.md"))


# ---------------------------------------------------------------------------
# 3. Policy check fail-closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_exception_denies_tool_call():
    """When policy evaluation throws, the tool call must be denied (fail-closed)."""
    from app.agent.tool_dispatch import dispatch_tool_call
    from app.config import settings

    orig = settings.TOOL_POLICY_ENABLED
    settings.TOOL_POLICY_ENABLED = True
    try:
        with (
            patch("app.agent.tool_dispatch._check_tool_policy", side_effect=RuntimeError("DB timeout")),
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock),
        ):
            result = await dispatch_tool_call(
                name="exec_command",
                args='{"command": "ls"}',
                tool_call_id="tc-1",
                bot_id="test-bot",
                bot_memory=None,
                session_id=None,
                client_id=None,
                correlation_id=None,
                channel_id=None,
                iteration=0,
                provider_id=None,
                summarize_enabled=False,
                summarize_threshold=10000,
                summarize_model="test",
                summarize_max_tokens=500,
                summarize_exclude=set(),
                compaction=False,
            )

            parsed = json.loads(result.result)
            assert "error" in parsed
            assert "denied" in parsed["error"].lower() or "policy" in parsed["error"].lower()
    finally:
        settings.TOOL_POLICY_ENABLED = orig


# ---------------------------------------------------------------------------
# 4. Task type validation
# ---------------------------------------------------------------------------

def test_task_create_rejects_exec_type():
    """TaskCreateIn must reject task_type='exec'."""
    from pydantic import ValidationError
    from app.routers.api_v1_admin.tasks import TaskCreateIn

    with pytest.raises(ValidationError) as exc_info:
        TaskCreateIn(prompt="test", bot_id="bot", task_type="exec")
    assert "task_type" in str(exc_info.value)


def test_task_create_rejects_harness_type():
    """TaskCreateIn must reject task_type='harness'."""
    from pydantic import ValidationError
    from app.routers.api_v1_admin.tasks import TaskCreateIn

    with pytest.raises(ValidationError) as exc_info:
        TaskCreateIn(prompt="test", bot_id="bot", task_type="harness")
    assert "task_type" in str(exc_info.value)


def test_task_create_rejects_claude_code_type():
    """TaskCreateIn must reject task_type='claude_code'."""
    from pydantic import ValidationError
    from app.routers.api_v1_admin.tasks import TaskCreateIn

    with pytest.raises(ValidationError) as exc_info:
        TaskCreateIn(prompt="test", bot_id="bot", task_type="claude_code")
    assert "task_type" in str(exc_info.value)


def test_task_create_rejects_delegation_type():
    """TaskCreateIn must reject task_type='delegation'."""
    from pydantic import ValidationError
    from app.routers.api_v1_admin.tasks import TaskCreateIn

    with pytest.raises(ValidationError) as exc_info:
        TaskCreateIn(prompt="test", bot_id="bot", task_type="delegation")
    assert "task_type" in str(exc_info.value)


def test_task_create_allows_scheduled():
    """TaskCreateIn must accept task_type='scheduled'."""
    from app.routers.api_v1_admin.tasks import TaskCreateIn

    t = TaskCreateIn(prompt="test", bot_id="bot", task_type="scheduled")
    assert t.task_type == "scheduled"


def test_task_create_allows_agent():
    """TaskCreateIn must accept task_type='agent'."""
    from app.routers.api_v1_admin.tasks import TaskCreateIn

    t = TaskCreateIn(prompt="test", bot_id="bot", task_type="agent")
    assert t.task_type == "agent"


def test_task_create_default_is_scheduled():
    """TaskCreateIn default task_type should be 'scheduled'."""
    from app.routers.api_v1_admin.tasks import TaskCreateIn

    t = TaskCreateIn(prompt="test", bot_id="bot")
    assert t.task_type == "scheduled"


def test_task_update_rejects_exec_type():
    """TaskUpdateIn must reject task_type='exec'."""
    from pydantic import ValidationError
    from app.routers.api_v1_admin.tasks import TaskUpdateIn

    with pytest.raises(ValidationError) as exc_info:
        TaskUpdateIn(task_type="exec")
    assert "task_type" in str(exc_info.value)


def test_task_update_allows_none():
    """TaskUpdateIn must allow task_type=None (no change)."""
    from app.routers.api_v1_admin.tasks import TaskUpdateIn

    t = TaskUpdateIn()
    assert t.task_type is None


def test_task_update_allows_scheduled():
    """TaskUpdateIn must accept task_type='scheduled'."""
    from app.routers.api_v1_admin.tasks import TaskUpdateIn

    t = TaskUpdateIn(task_type="scheduled")
    assert t.task_type == "scheduled"
