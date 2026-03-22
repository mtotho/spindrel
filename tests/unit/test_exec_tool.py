"""Unit tests for delegate_to_exec tool: script building, validation, access control."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field

import pytest

from app.tools.local.exec_tool import (
    EXEC_OUTPUT_DIR,
    _validate_stream_to,
    build_exec_script,
)


# ---------------------------------------------------------------------------
# build_exec_script
# ---------------------------------------------------------------------------


class TestBuildExecScript:
    def test_simple_command(self):
        script = build_exec_script("python", ["-c", "print('hi')"], None, None)
        assert script == "python -c 'print('\"'\"'hi'\"'\"')'"

    def test_simple_command_no_args(self):
        script = build_exec_script("ls", None, None, None)
        assert script == "ls"

    def test_with_working_directory(self):
        script = build_exec_script("ls", ["-la"], "/workspace", None)
        assert script.startswith("cd /workspace && ")
        assert "ls -la" in script

    def test_with_stream_to(self):
        script = build_exec_script("python", ["run.py"], None, "/tmp/out.log")
        assert "mkdir -p" in script
        assert "tee /tmp/out.log" in script
        assert "PIPESTATUS" in script

    def test_with_working_directory_and_stream_to(self):
        script = build_exec_script("npm", ["test"], "/app", "/tmp/exec-output/abc.log")
        assert "cd /app" in script
        assert "mkdir -p" in script
        assert "tee" in script

    def test_command_injection_safe(self):
        # Args with shell metacharacters should be safely quoted
        script = build_exec_script("echo", ["hello; rm -rf /"], None, None)
        assert "rm -rf" in script  # present but quoted
        assert "echo 'hello; rm -rf /'" == script

    def test_working_directory_with_spaces(self):
        script = build_exec_script("ls", None, "/my project dir", None)
        assert "cd '/my project dir'" in script


# ---------------------------------------------------------------------------
# _validate_stream_to
# ---------------------------------------------------------------------------


class TestValidateStreamTo:
    def test_valid_tmp_path(self):
        assert _validate_stream_to("/tmp/exec-output/abc.log") is None

    def test_invalid_path_outside_tmp(self):
        err = _validate_stream_to("/etc/passwd")
        assert err is not None
        assert "/tmp/" in err

    def test_newline_in_path(self):
        err = _validate_stream_to("/tmp/foo\nbar")
        assert err is not None
        assert "invalid" in err.lower()

    def test_null_byte_in_path(self):
        err = _validate_stream_to("/tmp/foo\x00bar")
        assert err is not None


# ---------------------------------------------------------------------------
# delegate_to_exec access control
# ---------------------------------------------------------------------------


@dataclass
class FakeBotSandbox:
    enabled: bool = False
    image: str = "python:3.12-slim"
    network: str = "none"
    env: dict = field(default_factory=dict)
    ports: list = field(default_factory=list)
    mounts: list = field(default_factory=list)
    user: str = ""
    unrestricted: bool = False


@dataclass
class FakeBot:
    id: str = "test_bot"
    bot_sandbox: FakeBotSandbox = field(default_factory=FakeBotSandbox)
    docker_sandbox_profiles: list = field(default_factory=list)


class TestDelegateToExecAccessControl:
    @pytest.mark.asyncio
    async def test_access_granted_when_exec_access_true(self):
        bot = FakeBot(bot_sandbox=FakeBotSandbox(enabled=True))
        mock_exec_res = MagicMock()
        mock_exec_res.stdout = "hello"
        mock_exec_res.stderr = ""
        mock_exec_res.exit_code = 0
        mock_exec_res.truncated = False
        mock_exec_res.duration_ms = 100

        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.agent.context.current_bot_id") as mock_bot_id, \
             patch("app.services.sandbox.sandbox_service.exec_bot_local", new_callable=AsyncMock, return_value=mock_exec_res):
            mock_bot_id.get.return_value = "test_bot"
            from app.tools.local.exec_tool import delegate_to_exec
            result = await delegate_to_exec(command="echo", args=["hello"])
            data = json.loads(result)
            assert data["exit_code"] == 0
            assert data["stdout"] == "hello"

    @pytest.mark.asyncio
    async def test_no_sandbox_returns_error(self):
        bot = FakeBot(bot_sandbox=FakeBotSandbox(enabled=False))
        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.agent.context.current_bot_id") as mock_bot_id:
            mock_bot_id.get.return_value = "test_bot"
            from app.tools.local.exec_tool import delegate_to_exec
            result = await delegate_to_exec(command="ls")
            data = json.loads(result)
            assert "error" in data
            assert "sandbox" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_stream_to_returns_error(self):
        bot = FakeBot()
        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.agent.context.current_bot_id") as mock_bot_id:
            mock_bot_id.get.return_value = "test_bot"
            from app.tools.local.exec_tool import delegate_to_exec
            result = await delegate_to_exec(command="ls", stream_to="/etc/passwd")
            data = json.loads(result)
            assert "error" in data
            assert "/tmp/" in data["error"]

    @pytest.mark.asyncio
    async def test_sync_mode_with_stream_to(self):
        bot = FakeBot(bot_sandbox=FakeBotSandbox(enabled=True))
        mock_exec_res = MagicMock()
        mock_exec_res.stdout = "output"
        mock_exec_res.stderr = ""
        mock_exec_res.exit_code = 0
        mock_exec_res.truncated = False
        mock_exec_res.duration_ms = 50

        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.agent.context.current_bot_id") as mock_bot_id, \
             patch("app.services.sandbox.sandbox_service.exec_bot_local", new_callable=AsyncMock, return_value=mock_exec_res):
            mock_bot_id.get.return_value = "test_bot"
            from app.tools.local.exec_tool import delegate_to_exec
            result = await delegate_to_exec(command="python", args=["run.py"], stream_to="/tmp/out.log")
            data = json.loads(result)
            assert data["exit_code"] == 0
            assert data["output_file"] == "/tmp/out.log"
