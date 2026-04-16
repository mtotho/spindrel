"""Tests for integrations.claude_code.runner — CLI arg building, script building, result parsing, Docker execution."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.claude_code.runner import (
    ClaudeCodeResult,
    build_claude_cli_args,
    build_script,
    parse_exec_result,
    run_in_container,
)


# ---------------------------------------------------------------------------
# build_claude_cli_args
# ---------------------------------------------------------------------------
class TestBuildClaudeCliArgs:

    def test_minimal_args(self):
        args = build_claude_cli_args()
        assert args == ["--output-format", "json"]

    def test_bypass_permissions(self):
        args = build_claude_cli_args(permission_mode="bypassPermissions")
        assert "--dangerously-skip-permissions" in args
        assert "--output-format" in args

    def test_non_bypass_permission_mode_no_flag(self):
        args = build_claude_cli_args(permission_mode="default")
        assert "--dangerously-skip-permissions" not in args

    def test_max_turns(self):
        args = build_claude_cli_args(max_turns=10)
        idx = args.index("--max-turns")
        assert args[idx + 1] == "10"

    def test_model(self):
        args = build_claude_cli_args(model="claude-sonnet-4-20250514")
        idx = args.index("--model")
        assert args[idx + 1] == "claude-sonnet-4-20250514"

    def test_system_prompt(self):
        args = build_claude_cli_args(system_prompt="Be brief")
        idx = args.index("--system-prompt")
        assert args[idx + 1] == "Be brief"

    def test_resume_session(self):
        args = build_claude_cli_args(resume_session_id="sess-123")
        idx = args.index("--resume")
        assert args[idx + 1] == "sess-123"

    def test_allowed_tools(self):
        args = build_claude_cli_args(allowed_tools=["Read", "Write", "Bash"])
        tool_indices = [i for i, a in enumerate(args) if a == "--allowedTools"]
        assert len(tool_indices) == 3
        tools_found = [args[i + 1] for i in tool_indices]
        assert tools_found == ["Read", "Write", "Bash"]

    def test_all_args_combined(self):
        args = build_claude_cli_args(
            max_turns=5,
            model="opus",
            permission_mode="bypassPermissions",
            system_prompt="test",
            resume_session_id="s1",
            allowed_tools=["Read"],
        )
        assert "--output-format" in args
        assert "--dangerously-skip-permissions" in args
        assert "--max-turns" in args
        assert "--model" in args
        assert "--system-prompt" in args
        assert "--resume" in args
        assert "--allowedTools" in args


# ---------------------------------------------------------------------------
# build_script
# ---------------------------------------------------------------------------
class TestBuildScript:

    def test_basic_script_with_working_dir(self):
        script = build_script("fix the bug", ["--output-format", "json"], working_directory="/workspace/repo")
        assert "cd " in script
        assert "/workspace/repo" in script
        assert "claude" in script
        assert "--output-format" in script
        assert "-p" in script
        assert "fix the bug" in script
        assert "<<'" in script  # heredoc

    def test_script_no_working_dir(self):
        script = build_script("hello", ["--output-format", "json"])
        assert "cd " not in script
        assert "claude" in script
        assert "hello" in script

    def test_prompt_not_in_command_portion(self):
        """Prompt should only appear in heredoc body, not in the shlex-joined command."""
        script = build_script("dangerous ; rm -rf /", ["--output-format", "json"])
        before_heredoc = script.split("<<")[0]
        assert "dangerous" not in before_heredoc

    def test_heredoc_delimiter_is_unique(self):
        s1 = build_script("a", [])
        s2 = build_script("a", [])
        d1 = s1.split("<<'")[1].split("'")[0]
        d2 = s2.split("<<'")[1].split("'")[0]
        assert d1 != d2


# ---------------------------------------------------------------------------
# parse_exec_result
# ---------------------------------------------------------------------------
class TestParseExecResult:

    def _make_claude_json(self, **overrides) -> str:
        data = {
            "type": "result",
            "result": "Done!",
            "session_id": "sess-abc",
            "is_error": False,
            "cost_usd": 0.05,
            "num_turns": 3,
            "duration_api_ms": 1500,
        }
        data.update(overrides)
        return json.dumps(data)

    def test_valid_json_output(self):
        stdout = self._make_claude_json()
        result = parse_exec_result(stdout, "", 0, 2000)
        assert result.result == "Done!"
        assert result.session_id == "sess-abc"
        assert result.is_error is False
        assert result.cost_usd == 0.05
        assert result.num_turns == 3
        assert result.duration_api_ms == 1500
        assert result.exit_code == 0
        assert result.duration_ms == 2000

    def test_json_with_error_flag(self):
        stdout = self._make_claude_json(is_error=True, result="Something failed")
        result = parse_exec_result(stdout, "", 0, 1000)
        assert result.is_error is True
        assert result.result == "Something failed"

    def test_non_json_success(self):
        result = parse_exec_result("plain text output", "", 0, 500)
        assert result.result == "plain text output"
        assert result.is_error is False
        assert result.session_id is None

    def test_non_json_failure(self):
        result = parse_exec_result("error message", "some stderr", 1, 300)
        assert result.result == "error message"
        assert result.is_error is True
        assert result.stderr == "some stderr"

    def test_empty_stdout_failure(self):
        result = parse_exec_result("", "", 1, 100)
        assert result.is_error is True
        assert "exited with code 1" in result.result

    def test_invalid_json(self):
        result = parse_exec_result("{not valid json", "", 0, 100)
        assert result.result == "{not valid json"
        assert result.is_error is False

    def test_json_missing_type_result(self):
        stdout = json.dumps({"some": "data"})
        result = parse_exec_result(stdout, "", 0, 100)
        assert result.session_id is None

    def test_stderr_preserved(self):
        stdout = self._make_claude_json()
        result = parse_exec_result(stdout, "warning: something", 0, 100)
        assert result.stderr == "warning: something"


# ---------------------------------------------------------------------------
# run_in_container
# ---------------------------------------------------------------------------
class TestRunInContainer:

    def _make_bot(self, **overrides):
        from app.agent.bots import BotConfig, MemoryConfig
        defaults = dict(
            id="test_bot",
            name="Test Bot",
            model="gpt-4",
            system_prompt="You are a test bot.",
            memory=MemoryConfig(),
        )
        defaults.update(overrides)
        return BotConfig(**defaults)

    @pytest.mark.asyncio
    async def test_bot_without_workspace_raises(self):
        bot = self._make_bot()
        bot.workspace = MagicMock(enabled=False)

        with patch("app.agent.bots.get_bot", return_value=bot):
            with pytest.raises(ValueError, match="no workspace enabled"):
                await run_in_container(bot_id="test_bot", prompt="hello")

    @pytest.mark.asyncio
    async def test_bot_without_docker_image_raises(self):
        bot = self._make_bot()
        bot.workspace = MagicMock(enabled=True)
        bot.workspace.docker = MagicMock(image="")

        with patch("app.agent.bots.get_bot", return_value=bot):
            with pytest.raises(ValueError, match="no Docker workspace"):
                await run_in_container(bot_id="test_bot", prompt="hello")

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        bot = self._make_bot()
        bot.workspace = MagicMock(enabled=True)
        bot.workspace.docker = MagicMock(image="workspace:latest", mounts=[], network="none", env={}, ports=[], user="")
        bot.shared_workspace_id = None

        json_output = json.dumps({
            "type": "result",
            "result": "File created",
            "session_id": "sess-xyz",
            "is_error": False,
            "cost_usd": 0.02,
            "num_turns": 2,
            "duration_api_ms": 800,
        })

        mock_exec_result = MagicMock(
            stdout=json_output, stderr="", exit_code=0,
            truncated=False, duration_ms=1500,
        )

        mock_settings = MagicMock()
        mock_settings.MAX_TURNS = 30
        mock_settings.TIMEOUT = 1800
        mock_settings.ALLOWED_TOOLS = ["Read", "Write"]
        mock_settings.PERMISSION_MODE = "bypassPermissions"
        mock_settings.MODEL = None

        mock_sandbox_config = MagicMock()

        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.sandbox.workspace_to_sandbox_config", return_value=mock_sandbox_config), \
             patch("app.services.sandbox.sandbox_service") as mock_sandbox, \
             patch("integrations.claude_code.config.settings", mock_settings):
            mock_sandbox.exec_bot_local = AsyncMock(return_value=mock_exec_result)

            result = await run_in_container(bot_id="test_bot", prompt="create a file")

        assert result.result == "File created"
        assert result.session_id == "sess-xyz"
        assert result.cost_usd == 0.02
        assert result.exit_code == 0

        # Verify exec_bot_local was called with correct args
        call_args = mock_sandbox.exec_bot_local.call_args
        assert call_args[0][0] == "test_bot"
        script = call_args[0][1]
        assert "claude" in script
        assert "--dangerously-skip-permissions" in script
        assert "create a file" in script
        assert call_args[1]["timeout"] == 1800

    @pytest.mark.asyncio
    async def test_working_directory_appended(self):
        bot = self._make_bot()
        bot.workspace = MagicMock(enabled=True)
        bot.workspace.docker = MagicMock(image="ws:latest", mounts=[], network="none", env={}, ports=[], user="")
        bot.shared_workspace_id = None

        mock_exec_result = MagicMock(
            stdout=json.dumps({"type": "result", "result": "ok"}),
            stderr="", exit_code=0, truncated=False, duration_ms=100,
        )

        mock_settings = MagicMock()
        mock_settings.MAX_TURNS = 30
        mock_settings.TIMEOUT = 1800
        mock_settings.ALLOWED_TOOLS = []
        mock_settings.PERMISSION_MODE = "default"
        mock_settings.MODEL = None

        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.sandbox.workspace_to_sandbox_config", return_value=MagicMock()), \
             patch("app.services.sandbox.sandbox_service") as mock_sandbox, \
             patch("integrations.claude_code.config.settings", mock_settings):
            mock_sandbox.exec_bot_local = AsyncMock(return_value=mock_exec_result)

            await run_in_container(
                bot_id="test_bot", prompt="hi",
                working_directory="my-project/src",
            )

        script = mock_sandbox.exec_bot_local.call_args[0][1]
        assert "/workspace/my-project/src" in script

    @pytest.mark.asyncio
    async def test_custom_timeout_override(self):
        bot = self._make_bot()
        bot.workspace = MagicMock(enabled=True)
        bot.workspace.docker = MagicMock(image="ws:latest", mounts=[], network="none", env={}, ports=[], user="")
        bot.shared_workspace_id = None

        mock_exec_result = MagicMock(
            stdout=json.dumps({"type": "result", "result": "ok"}),
            stderr="", exit_code=0, truncated=False, duration_ms=100,
        )

        mock_settings = MagicMock()
        mock_settings.MAX_TURNS = 30
        mock_settings.TIMEOUT = 1800
        mock_settings.ALLOWED_TOOLS = []
        mock_settings.PERMISSION_MODE = "default"
        mock_settings.MODEL = None

        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.sandbox.workspace_to_sandbox_config", return_value=MagicMock()), \
             patch("app.services.sandbox.sandbox_service") as mock_sandbox, \
             patch("integrations.claude_code.config.settings", mock_settings):
            mock_sandbox.exec_bot_local = AsyncMock(return_value=mock_exec_result)

            await run_in_container(bot_id="test_bot", prompt="hi", timeout=600)

        assert mock_sandbox.exec_bot_local.call_args[1]["timeout"] == 600

    @pytest.mark.asyncio
    async def test_resume_session_in_cli_args(self):
        bot = self._make_bot()
        bot.workspace = MagicMock(enabled=True)
        bot.workspace.docker = MagicMock(image="ws:latest", mounts=[], network="none", env={}, ports=[], user="")
        bot.shared_workspace_id = None

        mock_exec_result = MagicMock(
            stdout=json.dumps({"type": "result", "result": "ok", "session_id": "sess-resume"}),
            stderr="", exit_code=0, truncated=False, duration_ms=100,
        )

        mock_settings = MagicMock()
        mock_settings.MAX_TURNS = 30
        mock_settings.TIMEOUT = 1800
        mock_settings.ALLOWED_TOOLS = []
        mock_settings.PERMISSION_MODE = "default"
        mock_settings.MODEL = None

        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.sandbox.workspace_to_sandbox_config", return_value=MagicMock()), \
             patch("app.services.sandbox.sandbox_service") as mock_sandbox, \
             patch("integrations.claude_code.config.settings", mock_settings):
            mock_sandbox.exec_bot_local = AsyncMock(return_value=mock_exec_result)

            result = await run_in_container(
                bot_id="test_bot", prompt="continue",
                resume_session_id="sess-old",
            )

        script = mock_sandbox.exec_bot_local.call_args[0][1]
        assert "--resume" in script
        assert "sess-old" in script


# ---------------------------------------------------------------------------
# workspace_to_sandbox_config
# ---------------------------------------------------------------------------
class TestWorkspaceToSandboxConfig:
    """Test the workspace_to_sandbox_config standalone function."""

    def _make_bot(self, *, shared_workspace_id=None, mounts=None, image="node:20"):
        from app.agent.bots import BotConfig, MemoryConfig, WorkspaceConfig, WorkspaceDockerConfig
        docker_cfg = WorkspaceDockerConfig(image=image, mounts=mounts or [])
        ws_cfg = WorkspaceConfig(enabled=True, type="docker", docker=docker_cfg)
        return BotConfig(
            id="test_bot", name="Test", model="gpt-4",
            system_prompt="test", memory=MemoryConfig(),
            workspace=ws_cfg,
            shared_workspace_id=shared_workspace_id,
        )

    def test_standalone_bot_mounts_workspace(self):
        from app.services.sandbox import workspace_to_sandbox_config
        bot = self._make_bot()

        with patch("app.services.workspace.workspace_service") as mock_ws, \
             patch("app.services.sandbox.local_to_host", side_effect=lambda x: x):
            mock_ws.ensure_host_dir.return_value = "/data/workspaces/test_bot"
            config = workspace_to_sandbox_config(bot)

        assert config.enabled is True
        assert config.unrestricted is True
        assert config.image == "node:20"
        assert any(m.get("container_path") == "/workspace" for m in config.mounts)

    def test_shared_workspace_bot_mounts_shared_root(self):
        from app.services.sandbox import workspace_to_sandbox_config
        bot = self._make_bot(shared_workspace_id="sw-123")

        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sw, \
             patch("app.services.sandbox.local_to_host", side_effect=lambda x: x):
            mock_sw.ensure_host_dirs.return_value = "/data/shared/sw-123"
            config = workspace_to_sandbox_config(bot)

        assert any(m.get("host_path") == "/data/shared/sw-123" for m in config.mounts)

    def test_existing_workspace_mount_not_duplicated(self):
        from app.services.sandbox import workspace_to_sandbox_config
        bot = self._make_bot(mounts=[{"host_path": "/custom", "container_path": "/workspace", "mode": "rw"}])

        with patch("app.services.workspace.workspace_service") as mock_ws, \
             patch("app.services.sandbox.local_to_host", side_effect=lambda x: x):
            mock_ws.ensure_host_dir.return_value = "/data/workspaces/test_bot"
            config = workspace_to_sandbox_config(bot)

        workspace_mounts = [m for m in config.mounts if m.get("container_path") == "/workspace"]
        assert len(workspace_mounts) == 1
        assert workspace_mounts[0]["host_path"] == "/custom"
