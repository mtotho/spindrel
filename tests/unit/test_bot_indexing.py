"""Boundary tests for app.services.bot_indexing.

Commit 1 scope: resolve_for(scope="workspace") pins that the new public
surface preserves the semantics of workspace_indexing.resolve_indexing +
get_all_roots. Memory + channel scopes arrive in later commits and are
pinned here as NotImplementedError so the boundary stays stable.
"""
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.bots import BotConfig, WorkspaceConfig, WorkspaceIndexingConfig
from app.services.bot_indexing import (
    BotIndexPlan,
    iter_watch_targets,
    reindex_bot,
    resolve_for,
)


def _make_bot(
    *,
    enabled: bool = True,
    shared_workspace_id: str | None = None,
    indexing: WorkspaceIndexingConfig | None = None,
    workspace_raw: dict | None = None,
    ws_indexing_config: dict | None = None,
) -> BotConfig:
    bot = BotConfig(
        id="test-bot",
        name="Test",
        model="m",
        system_prompt="",
        workspace=WorkspaceConfig(
            enabled=enabled,
            indexing=indexing or WorkspaceIndexingConfig(),
        ),
        shared_workspace_id=shared_workspace_id,
    )
    bot._workspace_raw = workspace_raw or {}
    bot._ws_indexing_config = ws_indexing_config
    return bot


class TestResolveForWorkspace:
    def test_returns_none_when_workspace_disabled(self):
        bot = _make_bot(enabled=False)
        assert resolve_for(bot, scope="workspace") is None

    def test_returns_plan_for_enabled_standalone_bot(self):
        bot = _make_bot(enabled=True)
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            plan = resolve_for(bot, scope="workspace")
        assert isinstance(plan, BotIndexPlan)
        assert plan.bot_id == "test-bot"
        assert plan.scope == "workspace"
        assert plan.roots == ("/data/test-bot",)
        assert plan.shared_workspace is False
        assert plan.skip_stale_cleanup is False

    def test_shared_workspace_uses_shared_root(self):
        bot = _make_bot(enabled=True, shared_workspace_id="ws-123")
        with patch("app.services.shared_workspace.shared_workspace_service") as mock_sws:
            mock_sws.get_host_root.return_value = "/data/shared/ws-123"
            plan = resolve_for(bot, scope="workspace")
        assert plan is not None
        assert plan.shared_workspace is True
        assert plan.roots == ("/data/shared/ws-123",)

    def test_plan_carries_cascade_defaults(self):
        bot = _make_bot(enabled=True)
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            plan = resolve_for(bot, scope="workspace")
        assert plan is not None
        assert plan.patterns == ["**/*.py", "**/*.md", "**/*.yaml"]
        assert plan.similarity_threshold == 0.30
        assert plan.top_k == 8
        assert plan.watch is True
        assert plan.cooldown_seconds == 300
        assert plan.segments is None

    def test_plan_reflects_workspace_level_segments(self):
        bot = _make_bot(
            enabled=True,
            ws_indexing_config={
                "segments": [{"path_prefix": "docs/", "patterns": ["**/*.md"]}],
            },
        )
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            plan = resolve_for(bot, scope="workspace")
        assert plan is not None
        assert plan.segments is not None
        assert plan.segments[0]["path_prefix"] == "docs/"
        assert plan.segments[0]["patterns"] == ["**/*.md"]

    def test_plan_reflects_bot_level_overrides(self):
        bot = _make_bot(
            enabled=True,
            indexing=WorkspaceIndexingConfig(
                patterns=["**/*.ts"],
                similarity_threshold=0.10,
                top_k=3,
                watch=False,
                cooldown_seconds=60,
            ),
            workspace_raw={
                "indexing": {
                    "patterns": ["**/*.ts"],
                    "similarity_threshold": 0.10,
                    "top_k": 3,
                    "watch": False,
                    "cooldown_seconds": 60,
                }
            },
        )
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            plan = resolve_for(bot, scope="workspace")
        assert plan is not None
        assert plan.patterns == ["**/*.ts"]
        assert plan.similarity_threshold == 0.10
        assert plan.top_k == 3
        assert plan.watch is False
        assert plan.cooldown_seconds == 60

    def test_plan_is_frozen(self):
        bot = _make_bot(enabled=True)
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            plan = resolve_for(bot, scope="workspace")
        assert plan is not None
        with pytest.raises(FrozenInstanceError):
            plan.bot_id = "other"  # type: ignore[misc]


class TestUnimplementedScopes:
    def test_memory_scope_raises_not_implemented(self):
        bot = _make_bot(enabled=True)
        with pytest.raises(NotImplementedError):
            resolve_for(bot, scope="memory")

    def test_channel_scope_raises_not_implemented(self):
        bot = _make_bot(enabled=True)
        with pytest.raises(NotImplementedError):
            resolve_for(bot, scope="channel")

    def test_unknown_scope_raises_value_error(self):
        bot = _make_bot(enabled=True)
        with pytest.raises(ValueError):
            resolve_for(bot, scope="garbage")  # type: ignore[arg-type]


class TestReindexBot:
    @pytest.mark.asyncio
    async def test_returns_none_when_workspace_disabled_and_no_memory(self):
        bot = _make_bot(enabled=False)
        bot.memory_scheme = None
        out = await reindex_bot(bot)
        assert out is None

    @pytest.mark.asyncio
    async def test_memory_only_bot_runs_memory_index(self):
        """Workspace enabled, memory_scheme=workspace-files, indexing.enabled=False."""
        bot = _make_bot(enabled=True)
        bot.memory_scheme = "workspace-files"
        with patch(
            "app.agent.fs_indexer.index_directory",
            new=AsyncMock(return_value={"indexed": 3, "skipped": 0, "removed": 0, "errors": 0}),
        ) as idx_mock, patch(
            "app.services.workspace.workspace_service"
        ) as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            out = await reindex_bot(bot, include_workspace=False)
        idx_mock.assert_awaited_once()
        _, kwargs = idx_mock.await_args
        assert kwargs["skip_stale_cleanup"] is True  # memory scope
        assert out is not None
        assert out["indexed"] == 3

    @pytest.mark.asyncio
    async def test_workspace_with_segments_indexes_each_root(self):
        bot = _make_bot(
            enabled=True,
            indexing=WorkspaceIndexingConfig(),
            ws_indexing_config={
                "segments": [{"path_prefix": "docs/", "patterns": ["**/*.md"]}],
            },
        )
        bot.workspace.indexing.enabled = True
        with patch(
            "app.agent.fs_indexer.index_directory",
            new=AsyncMock(return_value={"indexed": 5, "skipped": 1, "removed": 0, "errors": 0}),
        ) as idx_mock, patch(
            "app.agent.fs_indexer.cleanup_stale_roots", new=AsyncMock(return_value=0)
        ), patch(
            "app.services.workspace.workspace_service"
        ) as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            out = await reindex_bot(bot, include_memory=False)
        idx_mock.assert_awaited_once()
        _, kwargs = idx_mock.await_args
        assert kwargs["segments"][0]["path_prefix"] == "docs/"
        assert out is not None
        assert out["indexed"] == 5

    @pytest.mark.asyncio
    async def test_shared_workspace_no_segments_cleans_only_when_orphans_flag(self):
        """Shared-workspace-no-segments DB cleanup runs only with cleanup_orphans=True."""
        bot = _make_bot(enabled=True, shared_workspace_id="ws-123")
        bot.workspace.indexing.enabled = True
        with patch(
            "app.agent.fs_indexer.index_directory", new=AsyncMock()
        ) as idx_mock, patch(
            "app.agent.fs_indexer.cleanup_stale_roots", new=AsyncMock(return_value=0)
        ), patch(
            "app.services.shared_workspace.shared_workspace_service"
        ) as mock_sws, patch(
            "app.services.bot_indexing._cleanup_non_memory_chunks", new=AsyncMock()
        ) as cleanup_mock:
            mock_sws.get_host_root.return_value = "/data/shared/ws-123"
            # Without flag → cleanup skipped
            await reindex_bot(bot, include_memory=False, cleanup_orphans=False)
            cleanup_mock.assert_not_awaited()
            # With flag → cleanup runs once
            await reindex_bot(bot, include_memory=False, cleanup_orphans=True)
            cleanup_mock.assert_awaited_once()
        idx_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_orphans_trims_stale_roots(self):
        bot = _make_bot(enabled=True)
        bot.workspace.indexing.enabled = True
        with patch(
            "app.agent.fs_indexer.index_directory", new=AsyncMock()
        ), patch(
            "app.agent.fs_indexer.cleanup_stale_roots", new=AsyncMock(return_value=2)
        ) as stale_mock, patch(
            "app.services.workspace.workspace_service"
        ) as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            await reindex_bot(bot, include_memory=False, cleanup_orphans=True)
        stale_mock.assert_awaited_once_with("test-bot", ["/data/test-bot"])

    @pytest.mark.asyncio
    async def test_periodic_force_false_propagates(self):
        bot = _make_bot(enabled=True)
        bot.memory_scheme = "workspace-files"
        bot.workspace.indexing.enabled = True
        bot._ws_indexing_config = {
            "segments": [{"path_prefix": "docs/", "patterns": ["**/*.md"]}],
        }
        with patch(
            "app.agent.fs_indexer.index_directory",
            new=AsyncMock(return_value={"indexed": 0, "skipped": 2, "removed": 0, "errors": 0}),
        ) as idx_mock, patch(
            "app.agent.fs_indexer.cleanup_stale_roots", new=AsyncMock(return_value=0)
        ), patch(
            "app.services.workspace.workspace_service"
        ) as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            await reindex_bot(bot, force=False)
        # index_directory called twice: once for memory, once for workspace segments
        assert idx_mock.await_count == 2
        for call in idx_mock.await_args_list:
            assert call.kwargs["force"] is False

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_abort_workspace(self):
        bot = _make_bot(enabled=True)
        bot.memory_scheme = "workspace-files"
        bot.workspace.indexing.enabled = True
        bot._ws_indexing_config = {
            "segments": [{"path_prefix": "docs/", "patterns": ["**/*.md"]}],
        }
        with patch(
            "app.services.bot_indexing._reindex_memory",
            new=AsyncMock(side_effect=RuntimeError("memory boom")),
        ), patch(
            "app.agent.fs_indexer.index_directory",
            new=AsyncMock(return_value={"indexed": 1, "skipped": 0, "removed": 0, "errors": 0}),
        ) as idx_mock, patch(
            "app.agent.fs_indexer.cleanup_stale_roots", new=AsyncMock(return_value=0)
        ), patch(
            "app.services.workspace.workspace_service"
        ) as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            out = await reindex_bot(bot)
        idx_mock.assert_awaited_once()
        assert out is not None
        assert out["indexed"] == 1


class TestIterWatchTargets:
    def test_skips_shared_workspace_bots(self):
        bot = _make_bot(enabled=True, shared_workspace_id="ws-123")
        with patch("app.services.shared_workspace.shared_workspace_service"):
            assert list(iter_watch_targets([bot])) == []

    def test_skips_disabled_workspace_bots(self):
        bot = _make_bot(enabled=False)
        assert list(iter_watch_targets([bot])) == []

    def test_workspace_indexing_yields_per_root(self):
        bot = _make_bot(enabled=True)
        bot.workspace.indexing.enabled = True
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            targets = list(iter_watch_targets([bot]))
        assert len(targets) == 1
        plan, root = targets[0]
        assert root == "/data/test-bot"
        assert plan.scope == "workspace"
        assert plan.bot_id == "test-bot"

    def test_watch_false_drops_workspace_target(self):
        bot = _make_bot(
            enabled=True,
            indexing=WorkspaceIndexingConfig(watch=False),
            workspace_raw={"indexing": {"watch": False}},
        )
        bot.workspace.indexing.enabled = True
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            targets = list(iter_watch_targets([bot]))
        assert targets == []

    def test_memory_only_bot_yields_memory_scope_plan(self):
        bot = _make_bot(enabled=True)
        bot.memory_scheme = "workspace-files"
        bot.workspace.indexing.enabled = False
        with patch("app.services.workspace.workspace_service") as mock_ws:
            mock_ws.get_workspace_root.return_value = "/data/test-bot"
            targets = list(iter_watch_targets([bot]))
        assert len(targets) == 1
        plan, root = targets[0]
        assert plan.scope == "memory"
        assert plan.patterns == ["memory/**/*.md"]
        assert plan.segments is None
        assert plan.skip_stale_cleanup is True
        assert root == "/data/test-bot"
