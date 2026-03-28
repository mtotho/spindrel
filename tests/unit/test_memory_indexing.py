"""Tests for app.services.memory_indexing — memory-specific indexing helpers."""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.bots import (
    BotConfig, KnowledgeConfig, MemoryConfig,
    WorkspaceConfig, WorkspaceIndexingConfig,
)


def _bot(
    bot_id="test_bot",
    memory_scheme="workspace-files",
    workspace_enabled=True,
    indexing_enabled=False,
    **kw,
) -> BotConfig:
    ws = WorkspaceConfig(
        enabled=workspace_enabled,
        indexing=WorkspaceIndexingConfig(enabled=indexing_enabled),
    )
    defaults = dict(
        id=bot_id, name="Test", model="gpt-4", system_prompt="You are helpful.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        memory_scheme=memory_scheme,
        workspace=ws,
    )
    defaults.update(kw)
    return BotConfig(**defaults)


class TestGetMemoryPatterns:
    def test_returns_correct_pattern(self):
        from app.services.memory_indexing import get_memory_patterns
        patterns = get_memory_patterns()
        assert patterns == ["memory/**/*.md"]

    def test_returns_new_list_each_time(self):
        from app.services.memory_indexing import get_memory_patterns
        a = get_memory_patterns()
        b = get_memory_patterns()
        assert a == b
        assert a is not b  # new list, not shared reference


class TestIndexMemoryForBot:
    @pytest.mark.asyncio
    async def test_skips_non_memory_scheme(self):
        from app.services.memory_indexing import index_memory_for_bot
        bot = _bot(memory_scheme=None)
        result = await index_memory_for_bot(bot)
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_workspace_disabled(self):
        from app.services.memory_indexing import index_memory_for_bot
        bot = _bot(workspace_enabled=False)
        result = await index_memory_for_bot(bot)
        assert result is None

    @pytest.mark.asyncio
    async def test_calls_index_directory(self):
        from app.services.memory_indexing import index_memory_for_bot
        bot = _bot(bot_id="mem_bot")

        mock_index = AsyncMock(return_value={"indexed": 2, "skipped": 1, "removed": 0, "errors": 0, "cooldown": False})
        with (
            patch("app.agent.fs_indexer.index_directory", mock_index),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/mem_bot"]),
            patch("app.services.workspace.workspace_service"),
        ):
            result = await index_memory_for_bot(bot)

        assert result is not None
        assert result["indexed"] == 2
        assert result["skipped"] == 1
        mock_index.assert_called_once_with(
            "/ws/mem_bot", "mem_bot", ["memory/**/*.md"], force=True,
        )

    @pytest.mark.asyncio
    async def test_merges_stats_from_multiple_roots(self):
        from app.services.memory_indexing import index_memory_for_bot
        bot = _bot(bot_id="multi_root")

        stats_a = {"indexed": 3, "skipped": 0, "removed": 1, "errors": 0, "cooldown": False}
        stats_b = {"indexed": 1, "skipped": 2, "removed": 0, "errors": 1, "cooldown": False}
        mock_index = AsyncMock(side_effect=[stats_a, stats_b])
        with (
            patch("app.agent.fs_indexer.index_directory", mock_index),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/root1", "/ws/root2"]),
            patch("app.services.workspace.workspace_service"),
        ):
            result = await index_memory_for_bot(bot)

        assert result["indexed"] == 4
        assert result["skipped"] == 2
        assert result["removed"] == 1
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_works_with_indexing_enabled_bot(self):
        """A bot can have both indexing enabled AND memory_scheme — memory indexing still works."""
        from app.services.memory_indexing import index_memory_for_bot
        bot = _bot(bot_id="both_bot", indexing_enabled=True)

        mock_index = AsyncMock(return_value={"indexed": 1, "skipped": 0, "removed": 0, "errors": 0, "cooldown": False})
        with (
            patch("app.agent.fs_indexer.index_directory", mock_index),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/both_bot"]),
            patch("app.services.workspace.workspace_service"),
        ):
            result = await index_memory_for_bot(bot)

        assert result is not None
        assert result["indexed"] == 1
