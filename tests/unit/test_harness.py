"""Tests for harness service — path translation for shared workspace bots."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestSharedWorkspacePathTranslation:
    """Verify that working_directory is rewritten when the bot is in a shared workspace."""

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
    async def test_subdir_path_translated(self):
        """Nested path under the bot prefix should be rewritten."""
        svc = self._setup_service()
        bot = _make_bot(shared_workspace_id="ws-123")
        bot.workspace = MagicMock(enabled=True, type="docker")

        captured_wd = {}
        original_run = svc._run_in_bot_sandbox

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

        assert captured_wd["wd"] == "/workspace/repo/mission-control"

    @pytest.mark.asyncio
    async def test_exact_prefix_translated(self):
        """Exact bot prefix path should become /workspace."""
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
                working_directory="/workspace/bots/dev_bot",
                bot=bot,
            )

        assert captured_wd["wd"] == "/workspace"

    @pytest.mark.asyncio
    async def test_non_shared_bot_no_translation(self):
        """Non-shared-workspace bot paths should pass through unchanged."""
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
                working_directory="/workspace/bots/dev_bot/repo/mission-control",
                bot=bot,
            )

        assert captured_wd["wd"] == "/workspace/bots/dev_bot/repo/mission-control"

    @pytest.mark.asyncio
    async def test_different_bot_prefix_no_translation(self):
        """Path with a different bot's prefix should not be translated."""
        svc = self._setup_service()
        bot = _make_bot(id="dev_bot", shared_workspace_id="ws-123")
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
                working_directory="/workspace/bots/other_bot/repo/foo",
                bot=bot,
            )

        # Should NOT translate — this is another bot's path
        assert captured_wd["wd"] == "/workspace/bots/other_bot/repo/foo"

    @pytest.mark.asyncio
    async def test_plain_workspace_path_no_translation(self):
        """Path that's already /workspace/… (no bots/ prefix) passes through."""
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
                working_directory="/workspace/repo/foo",
                bot=bot,
            )

        assert captured_wd["wd"] == "/workspace/repo/foo"
