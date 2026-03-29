"""Tests for harness service — shared workspace mount and path handling."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.harness import HarnessConfig, HarnessService


def _make_bot(**overrides):
    from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig

    defaults = dict(
        id="dev_bot",
        name="Dev Bot",
        model="gpt-4",
        system_prompt="You are a dev bot.",
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
        shared_workspace_id=None,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


class TestWorkspaceToSandboxConfig:
    """Verify that _workspace_to_sandbox_config mounts the correct root."""

    def test_shared_workspace_mounts_full_root(self):
        """Shared workspace bot should mount the entire shared workspace, not just bots/{id}/."""
        bot = _make_bot(shared_workspace_id="ws-123")
        bot.workspace = MagicMock(enabled=True, type="docker")
        bot.workspace.docker.mounts = []
        bot.workspace.docker.image = "agent-workspace:latest"
        bot.workspace.docker.network = None
        bot.workspace.docker.env = {}
        bot.workspace.docker.ports = []
        bot.workspace.docker.user = None

        with patch("app.services.harness.local_to_host", side_effect=lambda p: p), \
             patch(
                 "app.services.shared_workspace.shared_workspace_service.ensure_host_dirs",
                 return_value="/fake/shared/ws-123",
             ) as mock_ensure:
            config = HarnessService._workspace_to_sandbox_config(bot)

        mock_ensure.assert_called_once_with("ws-123")
        ws_mount = next(m for m in config.mounts if m["container_path"] == "/workspace")
        assert ws_mount["host_path"] == "/fake/shared/ws-123"

    def test_standalone_bot_mounts_bot_dir(self):
        """Non-shared bot should mount its own workspace directory."""
        bot = _make_bot(shared_workspace_id=None)
        bot.workspace = MagicMock(enabled=True, type="docker")
        bot.workspace.docker.mounts = []
        bot.workspace.docker.image = "agent-workspace:latest"
        bot.workspace.docker.network = None
        bot.workspace.docker.env = {}
        bot.workspace.docker.ports = []
        bot.workspace.docker.user = None

        with patch("app.services.harness.local_to_host", side_effect=lambda p: p), \
             patch(
                 "app.services.workspace.workspace_service.ensure_host_dir",
                 return_value="/fake/workspaces/dev_bot",
             ) as mock_ensure:
            config = HarnessService._workspace_to_sandbox_config(bot)

        mock_ensure.assert_called_once_with("dev_bot", bot=bot)
        ws_mount = next(m for m in config.mounts if m["container_path"] == "/workspace")
        assert ws_mount["host_path"] == "/fake/workspaces/dev_bot"


class TestSharedWorkspacePathPassthrough:
    """Verify that working_directory passes through unchanged (no translation needed
    since the harness mounts the full shared workspace)."""

    def _setup_service(self) -> HarnessService:
        svc = HarnessService()
        svc._configs["claude"] = HarnessConfig(
            name="claude",
            command="claude",
            args=["-p", "{prompt}"],
            timeout=300,
        )
        return svc

    @pytest.mark.asyncio
    async def test_shared_bot_path_passes_through(self):
        """Shared workspace bot paths pass through unchanged to the harness container."""
        svc = self._setup_service()
        bot = _make_bot(shared_workspace_id="ws-123")
        bot.workspace = MagicMock(enabled=True, type="docker")

        captured_wd = {}

        async def spy(**kwargs):
            captured_wd["wd"] = kwargs.get("working_directory")
            return MagicMock(stdout="ok", stderr="", exit_code=0, truncated=False, duration_ms=100)

        with patch.object(svc, "_workspace_to_sandbox_config", return_value=MagicMock()), \
             patch.object(svc, "_run_in_bot_sandbox", side_effect=spy):
            await svc.run(
                "claude",
                prompt="hello",
                working_directory="/workspace/bots/dev_bot/repo/mission-control",
                bot=bot,
            )

        assert captured_wd["wd"] == "/workspace/bots/dev_bot/repo/mission-control"

    @pytest.mark.asyncio
    async def test_non_shared_bot_path_passes_through(self):
        """Non-shared-workspace bot paths also pass through unchanged."""
        svc = self._setup_service()
        bot = _make_bot(shared_workspace_id=None)
        bot.workspace = MagicMock(enabled=True, type="docker")

        captured_wd = {}

        async def spy(**kwargs):
            captured_wd["wd"] = kwargs.get("working_directory")
            return MagicMock(stdout="ok", stderr="", exit_code=0, truncated=False, duration_ms=100)

        with patch.object(svc, "_workspace_to_sandbox_config", return_value=MagicMock()), \
             patch.object(svc, "_run_in_bot_sandbox", side_effect=spy):
            await svc.run(
                "claude",
                prompt="hello",
                working_directory="/workspace/repo/foo",
                bot=bot,
            )

        assert captured_wd["wd"] == "/workspace/repo/foo"
