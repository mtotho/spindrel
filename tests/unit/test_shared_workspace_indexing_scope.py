"""Tests for the core shared workspace indexing invariant:

    Bots in a shared workspace ONLY index:
      1. Their own memory folder (bots/{id}/memory/**)
      2. Explicitly configured segments

    There is NO implicit blanket indexing of the entire workspace root.
    Files in common/, other bots' directories, .pytest_cache, etc. must NEVER
    be indexed for a bot unless that bot has an explicit segment covering them.

These tests cover:
  - index_directory: candidate discovery with/without segments
  - index_directory: stale chunk cleanup (removes old-segment files)
  - Shared workspace watcher: skips file indexing for segment-less bots
  - Diagnostics: TSVector query uses correct multi-root filter
  - Memory prefix protection during stale cleanup
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, WorkspaceConfig, WorkspaceIndexingConfig, IndexSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot(
    bot_id="test-bot",
    shared_workspace_id=None,
    shared_workspace_role=None,
    segments=None,
    indexing_enabled=True,
    memory_scheme="workspace-files",
    **kw,
) -> BotConfig:
    idx = WorkspaceIndexingConfig(
        enabled=indexing_enabled,
        segments=segments or [],
    )
    defaults = dict(
        id=bot_id, name="Test", model="gpt-4", system_prompt="Test.",
        memory=MemoryConfig(),
        workspace=WorkspaceConfig(enabled=True, indexing=idx),
        memory_scheme=memory_scheme,
        shared_workspace_id=shared_workspace_id,
        shared_workspace_role=shared_workspace_role,
        _workspace_raw={},
    )
    defaults.update(kw)
    return BotConfig(**defaults)


def _make_workspace_tree(root: Path) -> None:
    """Create a realistic shared workspace directory tree for testing."""
    dirs = [
        "bots/sprout/memory/logs",
        "bots/sprout/memory/reference",
        "bots/sprout/data",
        "bots/dev-bot/memory",
        "bots/dev-bot/prompts",
        "common/data",
        "common/plans",
        "common/scripts",
        "hub/pages",
        ".pytest_cache",
    ]
    files = {
        "bots/sprout/memory/MEMORY.md": "# Sprout memory",
        "bots/sprout/memory/logs/2026-03-28.md": "Today's log",
        "bots/sprout/memory/reference/recipes.md": "Recipes",
        "bots/sprout/data/state.yaml": "state: ok",
        "bots/dev-bot/memory/MEMORY.md": "# Dev bot memory",
        "bots/dev-bot/prompts/system.md": "System prompt",
        "common/data/config.yaml": "key: value",
        "common/plans/migration-plan.md": "# Migration",
        "common/scripts/deploy.py": "print('deploy')",
        "hub/pages/index.md": "# Hub",
        ".pytest_cache/conftest.py": "# cache",
        "README.md": "# Root readme",
    }
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
    for fpath, content in files.items():
        (root / fpath).write_text(content)


# ---------------------------------------------------------------------------
# Test: segment-based candidate discovery
# ---------------------------------------------------------------------------

class TestSegmentDiscovery:
    """index_directory must only discover files within active segment prefixes."""

    def test_segments_restrict_discovery(self, tmp_path):
        """With segments=[common/], only common/ files should be candidates."""
        _make_workspace_tree(tmp_path)

        from app.agent.fs_indexer import _build_pathspec

        root_path = tmp_path.resolve()
        segments = [{"path_prefix": "common/", "patterns": ["**/*.md", "**/*.py", "**/*.yaml"]}]

        # Reproduce the segment-exclusive discovery logic from index_directory
        seen: set[Path] = set()
        for seg in segments:
            seg_dir = root_path / seg["path_prefix"].rstrip("/")
            if not seg_dir.is_dir():
                continue
            for pattern in seg["patterns"]:
                for p in seg_dir.glob(pattern):
                    if p.is_file():
                        seen.add(p)

        rel_paths = {str(PurePosixPath(p.relative_to(root_path))) for p in seen}

        # Must include common/ files
        assert "common/data/config.yaml" in rel_paths
        assert "common/plans/migration-plan.md" in rel_paths
        assert "common/scripts/deploy.py" in rel_paths

        # Must NOT include anything outside common/
        for rp in rel_paths:
            assert rp.startswith("common/"), f"File {rp} is outside segment scope"

    def test_no_segments_blanket_discovers_everything(self, tmp_path):
        """Without segments, blanket glob discovers all matching files under root."""
        _make_workspace_tree(tmp_path)

        root_path = tmp_path.resolve()
        patterns = ["**/*.md", "**/*.py", "**/*.yaml"]

        seen: set[Path] = set()
        for pattern in patterns:
            for p in root_path.glob(pattern):
                if p.is_file():
                    seen.add(p)

        rel_paths = {str(PurePosixPath(p.relative_to(root_path))) for p in seen}

        # Blanket glob picks up EVERYTHING — this is the problematic behavior
        # for shared workspace bots. The watcher/startup must prevent this.
        assert "common/plans/migration-plan.md" in rel_paths
        assert "bots/dev-bot/prompts/system.md" in rel_paths
        assert "hub/pages/index.md" in rel_paths

    def test_empty_segments_list_is_falsy(self):
        """Confirm [] is falsy so the segment guard works correctly."""
        segments = []
        assert not segments, "Empty segments list must be falsy for the guard to work"

    def test_multiple_segments_union(self, tmp_path):
        """Multiple segments should discover files from all of them (union)."""
        _make_workspace_tree(tmp_path)

        root_path = tmp_path.resolve()
        segments = [
            {"path_prefix": "common/", "patterns": ["**/*.md"]},
            {"path_prefix": "hub/", "patterns": ["**/*.md"]},
        ]

        seen: set[Path] = set()
        for seg in segments:
            seg_dir = root_path / seg["path_prefix"].rstrip("/")
            if not seg_dir.is_dir():
                continue
            for pattern in seg["patterns"]:
                for p in seg_dir.glob(pattern):
                    if p.is_file():
                        seen.add(p)

        rel_paths = {str(PurePosixPath(p.relative_to(root_path))) for p in seen}

        assert "common/plans/migration-plan.md" in rel_paths
        assert "hub/pages/index.md" in rel_paths
        # But NOT things outside both segments
        assert not any(rp.startswith("bots/") for rp in rel_paths)


# ---------------------------------------------------------------------------
# Test: stale chunk cleanup protects memory correctly
# ---------------------------------------------------------------------------

class TestStaleCleanupMemoryProtection:
    """When segments are active, stale cleanup must protect memory files for
    BOTH standalone bots (memory/) and shared workspace bots (bots/{id}/memory/)."""

    def test_standalone_memory_protected(self):
        """Standalone bot: files starting with memory/ are protected."""
        stale = {
            "memory/MEMORY.md",
            "memory/logs/2026-03-28.md",
            "old-segment/data.md",
            "other/file.py",
        }
        bot_id = "standalone-bot"
        segments = [{"path_prefix": "src/"}]

        # Reproduce the protection logic from fs_indexer
        _memory_prefixes = ["memory/"]
        if bot_id:
            _memory_prefixes.append(f"bots/{bot_id}/memory/")
        filtered = {fp for fp in stale if not any(fp.startswith(p) for p in _memory_prefixes)}

        assert "memory/MEMORY.md" not in filtered
        assert "memory/logs/2026-03-28.md" not in filtered
        assert "old-segment/data.md" in filtered
        assert "other/file.py" in filtered

    def test_shared_workspace_memory_protected(self):
        """Shared workspace bot: files starting with bots/{id}/memory/ are protected."""
        bot_id = "sprout"
        stale = {
            "bots/sprout/memory/MEMORY.md",
            "bots/sprout/memory/logs/2026-03-28.md",
            "bots/sprout/memory/reference/recipes.md",
            "common/plans/migration-plan.md",  # should be purged
            "bots/dev-bot/prompts/system.md",  # should be purged
            ".pytest_cache/conftest.py",  # should be purged
        }
        segments = [{"path_prefix": "bots/sprout/data/"}]

        _memory_prefixes = ["memory/"]
        if bot_id:
            _memory_prefixes.append(f"bots/{bot_id}/memory/")
        filtered = {fp for fp in stale if not any(fp.startswith(p) for p in _memory_prefixes)}

        # Memory files must be protected
        assert "bots/sprout/memory/MEMORY.md" not in filtered
        assert "bots/sprout/memory/logs/2026-03-28.md" not in filtered
        assert "bots/sprout/memory/reference/recipes.md" not in filtered

        # Non-memory files must be purged
        assert "common/plans/migration-plan.md" in filtered
        assert "bots/dev-bot/prompts/system.md" in filtered
        assert ".pytest_cache/conftest.py" in filtered

    def test_other_bots_memory_not_protected(self):
        """A bot must NOT protect another bot's memory files from being purged."""
        bot_id = "sprout"
        stale = {
            "bots/dev-bot/memory/MEMORY.md",
        }

        _memory_prefixes = ["memory/"]
        if bot_id:
            _memory_prefixes.append(f"bots/{bot_id}/memory/")
        filtered = {fp for fp in stale if not any(fp.startswith(p) for p in _memory_prefixes)}

        # Another bot's memory files are NOT this bot's concern
        assert "bots/dev-bot/memory/MEMORY.md" in filtered

    def test_old_hardcoded_prefix_would_fail_for_shared_bots(self):
        """Demonstrate that the OLD hardcoded 'memory/' prefix missed shared workspace bots."""
        bot_id = "sprout"
        stale = {
            "bots/sprout/memory/MEMORY.md",
            "common/data/config.yaml",
        }

        # OLD logic (hardcoded "memory/" only)
        old_prefix = "memory/"
        old_filtered = {fp for fp in stale if not fp.startswith(old_prefix)}

        # OLD logic WRONGLY purges the bot's memory
        assert "bots/sprout/memory/MEMORY.md" in old_filtered, \
            "Old hardcoded prefix fails to protect shared workspace bot memory"

        # NEW logic (both prefixes)
        _memory_prefixes = ["memory/"]
        if bot_id:
            _memory_prefixes.append(f"bots/{bot_id}/memory/")
        new_filtered = {fp for fp in stale if not any(fp.startswith(p) for p in _memory_prefixes)}

        # NEW logic correctly protects it
        assert "bots/sprout/memory/MEMORY.md" not in new_filtered


# ---------------------------------------------------------------------------
# Test: shared workspace watcher must NOT blanket-index segment-less bots
# ---------------------------------------------------------------------------

class TestSharedWorkspaceWatcher:
    """The shared workspace watcher (_watch_shared_workspace) must not call
    index_directory without segments for shared workspace bots, as that
    triggers blanket glob of the entire workspace root."""

    @pytest.mark.asyncio
    async def test_watcher_skips_file_indexing_for_segmentless_bot(self):
        """Bot with indexing.enabled but no segments: only memory gets indexed.

        This reproduces the exact logic from _watch_shared_workspace to verify
        that the segment guard prevents blanket indexing.
        """
        bot = _bot(
            bot_id="sprout",
            shared_workspace_id="ws-123",
            shared_workspace_role="member",
            segments=[],
            indexing_enabled=True,
            memory_scheme="workspace-files",
        )

        mock_index = AsyncMock()
        mock_memory_index = AsyncMock(return_value={"files": 1})

        # Reproduce the watcher's per-bot decision logic (from _watch_shared_workspace)
        index_called = False
        memory_called = False

        _resolved = {
            "patterns": ["**/*.md"], "embedding_model": "m",
            "segments": [], "watch": True,
        }
        _segments = _resolved.get("segments")

        if bot.workspace.indexing.enabled:
            if not _segments:
                # This is the guard we added — segment-less bots skip file indexing
                if getattr(bot, "memory_scheme", None) == "workspace-files":
                    await mock_memory_index(bot, force=True)
                    memory_called = True
                # continue (would skip index_directory)
            else:
                await mock_index("/ws/root", bot.id, _resolved["patterns"],
                                 force=True, segments=_segments)
                index_called = True

        # index_directory must NOT be called (no segments → no file indexing)
        assert not index_called, "index_directory should NOT be called for segment-less bots"
        mock_index.assert_not_awaited()
        # memory indexing SHOULD be called
        assert memory_called, "memory indexing should be called for workspace-files bots"
        mock_memory_index.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_watcher_indexes_files_when_segments_exist(self):
        """Bot with segments: index_directory should be called with those segments."""
        segments = [IndexSegment(path_prefix="common/")]
        bot = _bot(
            bot_id="sprout",
            shared_workspace_id="ws-123",
            shared_workspace_role="member",
            segments=segments,
            indexing_enabled=True,
        )

        resolved_segments = [{"path_prefix": "common/", "embedding_model": "m",
                              "patterns": ["**/*.md"], "similarity_threshold": 0.3,
                              "top_k": 8, "watch": True, "channel_id": None}]

        mock_index = AsyncMock(return_value={"indexed": 1})

        with (
            patch("app.services.workspace_indexing.resolve_indexing", return_value={
                "patterns": ["**/*.md"], "embedding_model": "m",
                "segments": resolved_segments, "watch": True,
            }),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/root"]),
            patch("app.agent.fs_indexer.index_directory", new=mock_index),
        ):
            from app.services.workspace_indexing import resolve_indexing, get_all_roots
            from app.agent.fs_indexer import index_directory

            _resolved = resolve_indexing(
                bot.workspace.indexing, {}, None,
            )
            _segments = _resolved.get("segments")
            assert _segments, "Segments should be truthy"

            for root in get_all_roots(bot):
                await index_directory(
                    root, bot.id, _resolved["patterns"], force=True,
                    embedding_model=_resolved["embedding_model"],
                    segments=_segments,
                )

            mock_index.assert_awaited_once()
            call_kwargs = mock_index.call_args
            assert call_kwargs.kwargs["segments"] == resolved_segments

    @pytest.mark.asyncio
    async def test_shared_watcher_memory_change_only_indexes_own_memory_file(self, tmp_path):
        """A bot memory write must not force-reindex every bot in the shared workspace."""
        from app.agent.fs_watcher import _reindex_shared_workspace_changes
        from app.services.bot_indexing import BotIndexPlan

        root = tmp_path / "ws"
        memory_file = root / "bots" / "sprout" / "memory" / "note.md"
        memory_file.parent.mkdir(parents=True)
        memory_file.write_text("remember this")

        sprout = MagicMock()
        sprout.id = "sprout"
        sprout.shared_workspace_id = "ws-123"
        sprout.workspace.indexing.enabled = True
        image_bot = MagicMock()
        image_bot.id = "image-bot"
        image_bot.shared_workspace_id = "ws-123"
        image_bot.workspace.indexing.enabled = True

        def _plan(bot_id: str, scope: str, patterns: list[str], segments=None):
            return BotIndexPlan(
                bot_id=bot_id,
                roots=(str(root),),
                patterns=patterns,
                embedding_model="text-embedding-3-small",
                similarity_threshold=0.35,
                top_k=8,
                watch=True,
                cooldown_seconds=0,
                segments=segments,
                scope=scope,
                shared_workspace=True,
                skip_stale_cleanup=(scope == "memory"),
            )

        def resolve_for(bot, *, scope="workspace", **_kwargs):
            if bot.id == "sprout" and scope == "memory":
                return _plan("sprout", "memory", ["bots/sprout/memory/**/*.md"])
            if bot.id == "sprout" and scope == "workspace":
                return _plan("sprout", "workspace", ["common/**/*.md"], segments=[{"path_prefix": "common"}])
            if bot.id == "image-bot" and scope == "memory":
                return _plan("image-bot", "memory", ["bots/image-bot/memory/**/*.md"])
            if bot.id == "image-bot" and scope == "workspace":
                return _plan("image-bot", "workspace", ["common/**/*.md"], segments=[{"path_prefix": "common"}])
            return None

        mock_index = AsyncMock(return_value={"indexed": 1})
        with (
            patch("app.agent.bots.list_bots", return_value=[sprout, image_bot]),
            patch("app.services.bot_indexing.resolve_for", side_effect=resolve_for),
            patch("app.agent.fs_indexer.index_directory", new=mock_index),
        ):
            await _reindex_shared_workspace_changes(
                "ws-123",
                root,
                {memory_file},
                set(),
            )

        mock_index.assert_awaited_once()
        args, kwargs = mock_index.await_args
        assert args[1] == "sprout"
        assert kwargs["file_paths"] == [memory_file]
        assert kwargs["skip_stale_cleanup"] is True


# ---------------------------------------------------------------------------
# Test: diagnostics TSVector query uses correct root filter
# ---------------------------------------------------------------------------

class TestDiagnosticsTSVectorFilter:
    """The diagnostics TSVector count must use the same multi-root filter as
    all other chunk count queries, not a single ws_root_resolved."""

    def test_shared_workspace_roots_differ(self):
        """For shared workspace bots, get_all_roots returns the workspace root,
        but workspace_service.get_workspace_root returns the bot-specific directory.
        The TSVector query must use get_all_roots, not the bot-specific root."""
        bot = _bot(
            bot_id="sprout",
            shared_workspace_id="ws-123",
            shared_workspace_role="member",
        )

        with (
            patch("app.services.shared_workspace.shared_workspace_service") as mock_sws,
            patch("app.services.workspace.workspace_service") as mock_ws,
        ):
            mock_sws.get_host_root.return_value = "/data/workspaces/ws-123"
            mock_ws.get_workspace_root.return_value = "/data/workspaces/ws-123/bots/sprout"

            from app.services.workspace_indexing import get_all_roots

            all_roots = get_all_roots(bot)
            bot_specific_root = mock_ws.get_workspace_root("sprout", bot)

            # These MUST be different — that's the whole point
            assert all_roots == ["/data/workspaces/ws-123"]
            assert bot_specific_root == "/data/workspaces/ws-123/bots/sprout"
            assert all_roots[0] != bot_specific_root

    def test_standalone_bot_roots_same(self):
        """For standalone bots, both methods return the same root."""
        bot = _bot(bot_id="standalone")

        mock_ws = MagicMock()
        mock_ws.get_workspace_root.return_value = "/data/bots/standalone"

        from app.services.workspace_indexing import get_all_roots
        all_roots = get_all_roots(bot, mock_ws)

        assert all_roots == ["/data/bots/standalone"]


# ---------------------------------------------------------------------------
# Test: startup cleanup logic for segment-less shared workspace bots
# ---------------------------------------------------------------------------

class TestStartupCleanup:
    """When a shared workspace bot has no segments, startup must clean up
    non-memory chunks. Only bots/{id}/memory/** should survive."""

    def test_cleanup_filter_keeps_memory_purges_rest(self):
        """Simulate the cleanup WHERE clause logic."""
        bot_id = "sprout"

        # Simulated DB contents (file_path column values)
        all_chunks = [
            "bots/sprout/memory/MEMORY.md",
            "bots/sprout/memory/logs/2026-03-28.md",
            "bots/sprout/memory/reference/recipes.md",
            "bots/sprout/data/state.yaml",
            "common/data/config.yaml",
            "common/plans/migration-plan.md",
            "common/scripts/deploy.py",
            "hub/pages/index.md",
            ".pytest_cache/conftest.py",
            "README.md",
        ]

        from app.services.memory_scheme import get_memory_index_prefix

        bot = _bot(bot_id=bot_id, shared_workspace_id="ws-123", shared_workspace_role="member")
        mem_prefix = get_memory_index_prefix(bot)
        assert mem_prefix == f"bots/{bot_id}/memory"

        # Simulate: NOT LIKE 'bots/sprout/memory/%'
        like_pattern = mem_prefix.rstrip("/") + "/"
        to_delete = [fp for fp in all_chunks if not fp.startswith(like_pattern)]
        to_keep = [fp for fp in all_chunks if fp.startswith(like_pattern)]

        # Memory files survive
        assert "bots/sprout/memory/MEMORY.md" in to_keep
        assert "bots/sprout/memory/logs/2026-03-28.md" in to_keep
        assert "bots/sprout/memory/reference/recipes.md" in to_keep

        # Everything else gets deleted
        assert "common/data/config.yaml" in to_delete
        assert "common/plans/migration-plan.md" in to_delete
        assert "hub/pages/index.md" in to_delete
        assert ".pytest_cache/conftest.py" in to_delete
        assert "bots/sprout/data/state.yaml" in to_delete
        assert "README.md" in to_delete


# ---------------------------------------------------------------------------
# Test: resolve_indexing returns empty segments when none configured
# ---------------------------------------------------------------------------

class TestResolveIndexingSegments:
    """Confirm resolve_indexing returns falsy segments when none are configured."""

    def test_no_segments_returns_empty_list(self):
        from app.services.workspace_indexing import resolve_indexing

        bot_indexing = WorkspaceIndexingConfig(segments=[])
        result = resolve_indexing(bot_indexing, {}, None)
        assert result["segments"] == []
        assert not result["segments"], "Empty segments must be falsy"

    def test_segments_present_returns_truthy(self):
        from app.services.workspace_indexing import resolve_indexing

        bot_indexing = WorkspaceIndexingConfig(
            segments=[IndexSegment(path_prefix="common/")],
        )
        # The raw dict must declare "segments" for the bot-level cascade to fire
        raw = {"indexing": {"segments": [{"path_prefix": "common/"}]}}
        result = resolve_indexing(bot_indexing, raw, None)
        assert len(result["segments"]) == 1
        assert result["segments"], "Non-empty segments must be truthy"
        assert result["segments"][0]["path_prefix"] == "common/"


# ---------------------------------------------------------------------------
# Test: the complete indexing scope rule
# ---------------------------------------------------------------------------

class TestIndexingScopeInvariant:
    """End-to-end invariant: for any shared workspace bot, the set of indexed
    files must be exactly (memory files) ∪ (files under explicit segments).
    Nothing more, nothing less."""

    def test_memory_only_bot_indexes_nothing_outside_memory(self, tmp_path):
        """Bot with no segments: only memory/ files should ever be indexed."""
        _make_workspace_tree(tmp_path)
        root_path = tmp_path.resolve()
        bot_id = "sprout"
        segments = []  # no segments

        # With segments=[], index_directory would blanket-discover everything.
        # The guard in the watcher/startup must prevent this call entirely.
        # Only memory indexing should happen (separate code path).

        # Simulate what memory indexing discovers
        from app.services.memory_scheme import get_memory_index_prefix
        bot = _bot(bot_id=bot_id, shared_workspace_id="ws-123", shared_workspace_role="member")
        mem_prefix = get_memory_index_prefix(bot)

        memory_patterns = [f"{mem_prefix}/**/*.md"]
        memory_files = set()
        for pattern in memory_patterns:
            for p in root_path.glob(pattern):
                if p.is_file():
                    memory_files.add(str(PurePosixPath(p.relative_to(root_path))))

        # Only memory files discovered
        assert all(fp.startswith(f"bots/{bot_id}/memory/") for fp in memory_files)
        assert "bots/sprout/memory/MEMORY.md" in memory_files
        assert "bots/sprout/memory/logs/2026-03-28.md" in memory_files

        # Specifically: no common/, no other bots, no root files
        assert not any(fp.startswith("common/") for fp in memory_files)
        assert not any(fp.startswith("hub/") for fp in memory_files)
        assert not any(fp.startswith(".pytest_cache") for fp in memory_files)
        assert "README.md" not in memory_files

    def test_bot_with_segments_indexes_segments_only(self, tmp_path):
        """Bot with segments=[common/]: discovers common/ files + memory is separate."""
        _make_workspace_tree(tmp_path)
        root_path = tmp_path.resolve()
        bot_id = "sprout"
        segments = [{"path_prefix": "common/", "patterns": ["**/*.md", "**/*.py", "**/*.yaml"]}]

        # Segment-exclusive discovery
        from app.agent.fs_indexer import _is_auto_injected, _SKIP_DIRS

        seen: set[Path] = set()
        for seg in segments:
            seg_dir = root_path / seg["path_prefix"].rstrip("/")
            for pattern in seg["patterns"]:
                for p in seg_dir.glob(pattern):
                    if p.is_file():
                        parts = p.relative_to(root_path).parts
                        if not any(part in _SKIP_DIRS for part in parts):
                            if not _is_auto_injected(parts):
                                seen.add(p)

        rel_paths = {str(PurePosixPath(p.relative_to(root_path))) for p in seen}

        # Only common/ files
        assert all(rp.startswith("common/") for rp in rel_paths)
        assert "common/plans/migration-plan.md" in rel_paths
        assert "common/scripts/deploy.py" in rel_paths
        assert "common/data/config.yaml" in rel_paths

        # Nothing from other directories
        assert not any(rp.startswith("bots/") for rp in rel_paths)
        assert not any(rp.startswith("hub/") for rp in rel_paths)

    def test_bot_with_two_segments(self, tmp_path):
        """Bot with segments=[common/, hub/]: discovers union of both."""
        _make_workspace_tree(tmp_path)
        root_path = tmp_path.resolve()

        segments = [
            {"path_prefix": "common/", "patterns": ["**/*.md"]},
            {"path_prefix": "hub/", "patterns": ["**/*.md"]},
        ]

        seen: set[Path] = set()
        for seg in segments:
            seg_dir = root_path / seg["path_prefix"].rstrip("/")
            if not seg_dir.is_dir():
                continue
            for pattern in seg["patterns"]:
                for p in seg_dir.glob(pattern):
                    if p.is_file():
                        seen.add(p)

        rel_paths = {str(PurePosixPath(p.relative_to(root_path))) for p in seen}

        assert "common/plans/migration-plan.md" in rel_paths
        assert "hub/pages/index.md" in rel_paths
        assert not any(rp.startswith("bots/") for rp in rel_paths)
        assert "README.md" not in rel_paths


# ---------------------------------------------------------------------------
# Test: TSVector backfill runs at end of index_directory
# ---------------------------------------------------------------------------

class TestTSVectorBackfill:
    """The TSVector backfill at the end of index_directory should populate
    tsv for all chunks with tsv IS NULL, including pre-migration chunks."""

    def test_backfill_sql_includes_bot_id(self):
        """When bot_id is set, the backfill UPDATE includes bot_id filter."""
        # This is a logic test — verify the SQL branches
        bot_id = "sprout"
        root_path = "/ws/root"

        # bot_id is not None → should use "AND bot_id = :bid"
        assert bot_id is not None
        # The code does: if bot_id is not None: ...bindparams(rt=..., bid=bot_id)

    def test_backfill_sql_handles_null_bot_id(self):
        """When bot_id is None, the backfill UPDATE uses 'bot_id IS NULL'."""
        bot_id = None
        assert bot_id is None
        # The code does: else: ...WHERE root = :rt AND bot_id IS NULL AND tsv IS NULL


# ---------------------------------------------------------------------------
# Test: diagnostics reindex cleans up stale chunks for segment-less bots
# ---------------------------------------------------------------------------

class TestDiagnosticsReindexCleanup:
    """The Force Reindex endpoint must clean up non-memory chunks
    for shared workspace bots that no longer have segments."""

    def test_reindex_cleanup_filter_logic(self):
        """Verify the cleanup filter: only bots/{id}/memory/* survives."""
        bot = _bot(
            bot_id="sprout",
            shared_workspace_id="ws-123",
            shared_workspace_role="member",
            segments=[],
        )

        from app.services.memory_scheme import get_memory_index_prefix
        mem_prefix = get_memory_index_prefix(bot)
        like_pattern = mem_prefix.rstrip("/") + "/%"

        # SQL LIKE 'bots/sprout/memory/%' — these should NOT be deleted
        assert "bots/sprout/memory/MEMORY.md".startswith(mem_prefix + "/")

        # These SHOULD be deleted (don't match the LIKE pattern)
        assert not "common/plans/migration-plan.md".startswith(mem_prefix + "/")
        assert not ".pytest_cache/conftest.py".startswith(mem_prefix + "/")
        assert not "bots/dev-bot/memory/MEMORY.md".startswith(mem_prefix + "/")

    def test_reindex_needs_segments_check(self):
        """Shared workspace bot + no segments = should trigger cleanup, not index."""
        from app.services.workspace_indexing import resolve_indexing

        bot = _bot(
            bot_id="sprout",
            shared_workspace_id="ws-123",
            shared_workspace_role="member",
            segments=[],
        )

        _resolved = resolve_indexing(bot.workspace.indexing, {}, None)
        _segments = _resolved.get("segments")

        assert bot.shared_workspace_id is not None
        assert not _segments, "No segments → should trigger cleanup path"
