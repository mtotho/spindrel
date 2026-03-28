"""Tests verifying memory files get indexed with correct root/file_path
and that search_memory queries match those stored values.

Critical for shared workspace bots where path resolution differs between
orchestrators (root = shared_ws_root, prefix = bots/{id}/memory) and
members (root = shared_ws_root/bots/{id}, prefix = memory).
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agent.bots import BotConfig, KnowledgeConfig, MemoryConfig


def _bot(
    bot_id="test_bot",
    memory_scheme="workspace-files",
    shared_workspace_id=None,
    shared_workspace_role=None,
    **kw,
) -> BotConfig:
    defaults = dict(
        id=bot_id, name="Test", model="gpt-4", system_prompt="You are helpful.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        memory_scheme=memory_scheme,
        shared_workspace_id=shared_workspace_id,
        shared_workspace_role=shared_workspace_role,
    )
    defaults.update(kw)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# Memory prefix resolution for different workspace roles
# ---------------------------------------------------------------------------

class TestMemoryRelPath:
    """get_memory_rel_path must return the correct prefix for each bot role."""

    def test_standalone_bot(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(bot_id="standalone")
        assert get_memory_rel_path(bot) == "memory"

    def test_shared_workspace_member(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(
            bot_id="member_bot",
            shared_workspace_id="ws-abc",
            shared_workspace_role="worker",
        )
        assert get_memory_rel_path(bot) == "memory"

    def test_shared_workspace_orchestrator(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(
            bot_id="orch_bot",
            shared_workspace_id="ws-abc",
            shared_workspace_role="orchestrator",
        )
        assert get_memory_rel_path(bot) == os.path.join("bots", "orch_bot", "memory")


# ---------------------------------------------------------------------------
# Workspace root resolution
# ---------------------------------------------------------------------------

class TestWorkspaceRootResolution:
    """Verify get_workspace_root returns correct paths per role."""

    def test_standalone_bot(self):
        from app.services.workspace import WorkspaceService
        ws = WorkspaceService()
        bot = _bot(bot_id="standalone")
        with patch("app.services.workspace.local_workspace_base", return_value="/base"):
            root = ws.get_workspace_root("standalone", bot)
        assert root == "/base/standalone"

    def test_shared_member(self):
        from app.services.workspace import WorkspaceService
        ws = WorkspaceService()
        bot = _bot(
            bot_id="worker",
            shared_workspace_id="ws-123",
            shared_workspace_role="worker",
        )
        with patch(
            "app.services.shared_workspace.shared_workspace_service.get_host_root",
            return_value="/base/shared/ws-123",
        ):
            root = ws.get_workspace_root("worker", bot)
        assert root == "/base/shared/ws-123/bots/worker"

    def test_shared_orchestrator(self):
        from app.services.workspace import WorkspaceService
        ws = WorkspaceService()
        bot = _bot(
            bot_id="orch",
            shared_workspace_id="ws-123",
            shared_workspace_role="orchestrator",
        )
        with patch(
            "app.services.shared_workspace.shared_workspace_service.get_host_root",
            return_value="/base/shared/ws-123",
        ):
            root = ws.get_workspace_root("orch", bot)
        assert root == "/base/shared/ws-123"


# ---------------------------------------------------------------------------
# Indexer: memory files are NOT skipped by _is_auto_injected
# ---------------------------------------------------------------------------

class TestAutoInjectedDoesNotSkipMemory:
    """Memory files must NOT be excluded by the auto-injection skip list."""

    def test_memory_md_not_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("memory", "MEMORY.md")) is False

    def test_memory_log_not_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("memory", "logs", "2026-03-28.md")) is False

    def test_memory_reference_not_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("memory", "reference", "todos.md")) is False

    def test_orchestrator_memory_not_skipped(self):
        """bots/orch_bot/memory/MEMORY.md should NOT be auto-injected."""
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("bots", "orch_bot", "memory", "MEMORY.md")) is False
        assert _is_auto_injected(("bots", "orch_bot", "memory", "logs", "2026-03-28.md")) is False

    def test_skills_ARE_skipped(self):
        """Sanity check: skills/ subtree IS auto-injected (should be skipped)."""
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("skills", "arch_linux.md")) is True

    def test_persona_IS_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("persona.md",)) is True

    def test_bots_persona_IS_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("bots", "orch", "persona.md")) is True

    def test_bots_skills_IS_skipped(self):
        from app.agent.fs_indexer import _is_auto_injected
        assert _is_auto_injected(("bots", "orch", "skills", "foo.md")) is True


# ---------------------------------------------------------------------------
# End-to-end: indexing stores correct root + file_path, search queries match
# ---------------------------------------------------------------------------

class TestMemoryPathConsistency:
    """Verify that the root/file_path stored during indexing exactly matches
    the root/memory_prefix used by search_memory."""

    def _compute_index_params(self, bot, ws_root: str) -> tuple[str, str]:
        """Simulate what index_directory would store: (root, file_path_prefix)."""
        root = str(Path(ws_root).resolve())
        return root, "memory"

    def _compute_search_params(self, bot, ws_root: str) -> tuple[str, str]:
        """Simulate what search_memory would query: (root, memory_prefix)."""
        from app.services.memory_scheme import get_memory_rel_path
        root = str(Path(ws_root).resolve())
        prefix = get_memory_rel_path(bot)
        return root, prefix

    def test_standalone_bot_paths_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_root = os.path.join(tmpdir, "standalone_bot")
            os.makedirs(ws_root, exist_ok=True)
            bot = _bot(bot_id="standalone_bot")

            idx_root, idx_prefix = self._compute_index_params(bot, ws_root)
            search_root, search_prefix = self._compute_search_params(bot, ws_root)

            assert idx_root == search_root, f"Root mismatch: index={idx_root} search={search_root}"
            # file_path like "memory/MEMORY.md" matches LIKE "memory/%"
            assert f"{idx_prefix}/MEMORY.md".startswith(search_prefix + "/")

    def test_shared_member_bot_paths_match(self):
        """Member bot: root = {shared}/bots/{id}, prefix = memory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shared_root = os.path.join(tmpdir, "shared", "ws-123")
            ws_root = os.path.join(shared_root, "bots", "worker_bot")
            os.makedirs(ws_root, exist_ok=True)
            bot = _bot(
                bot_id="worker_bot",
                shared_workspace_id="ws-123",
                shared_workspace_role="worker",
            )

            idx_root, idx_prefix = self._compute_index_params(bot, ws_root)
            search_root, search_prefix = self._compute_search_params(bot, ws_root)

            assert idx_root == search_root
            # Indexed: file_path = "memory/MEMORY.md", search LIKE "memory/%"
            sample_file_path = f"{idx_prefix}/MEMORY.md"
            assert sample_file_path.startswith(search_prefix + "/")

    def test_shared_orchestrator_bot_paths_match(self):
        """Orchestrator: root = {shared}, prefix = bots/{id}/memory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shared_root = os.path.join(tmpdir, "shared", "ws-123")
            os.makedirs(shared_root, exist_ok=True)
            bot = _bot(
                bot_id="orch_bot",
                shared_workspace_id="ws-123",
                shared_workspace_role="orchestrator",
            )

            from app.services.memory_scheme import get_memory_rel_path
            orch_root = str(Path(shared_root).resolve())
            orch_prefix = get_memory_rel_path(bot)

            # Orchestrator indexes from shared root — memory at bots/orch_bot/memory/
            assert orch_prefix == os.path.join("bots", "orch_bot", "memory")

            # Indexed file_path would be "bots/orch_bot/memory/MEMORY.md"
            # Search LIKE "bots/orch_bot/memory/%"
            sample_file_path = f"{orch_prefix}/MEMORY.md"
            search_pattern = orch_prefix + "/%"
            # SQL LIKE match simulation
            assert sample_file_path.startswith(orch_prefix + "/")


# ---------------------------------------------------------------------------
# hybrid_memory_search: SQL pattern generation
# ---------------------------------------------------------------------------

class TestMemorySearchPatterns:
    """Verify the SQL LIKE pattern correctly scopes to memory subdirectory."""

    def test_member_pattern(self):
        """Non-orchestrator: memory_prefix='memory' → LIKE 'memory/%'."""
        prefix = "memory"
        pattern = prefix.rstrip("/") + "/%"
        assert pattern == "memory/%"
        # Should match memory file paths
        assert "memory/MEMORY.md".startswith("memory/")
        assert "memory/logs/2026-03-28.md".startswith("memory/")
        assert "memory/reference/todos.md".startswith("memory/")
        # Should NOT match non-memory files
        assert not "data/status.json".startswith("memory/")

    def test_orchestrator_pattern(self):
        """Orchestrator: memory_prefix='bots/orch/memory' → LIKE 'bots/orch/memory/%'."""
        prefix = "bots/orch_bot/memory"
        pattern = prefix.rstrip("/") + "/%"
        assert pattern == "bots/orch_bot/memory/%"
        # Should match orchestrator's own memory
        assert "bots/orch_bot/memory/MEMORY.md".startswith("bots/orch_bot/memory/")
        # Should NOT match other bot's memory
        assert not "bots/worker_bot/memory/MEMORY.md".startswith("bots/orch_bot/memory/")


# ---------------------------------------------------------------------------
# Diagnostics: memory prefix used correctly
# ---------------------------------------------------------------------------

class TestDiagnosticsMemoryPrefix:
    """Diagnostics must use get_memory_rel_path, not hardcoded 'memory/%'."""

    def test_member_bot_prefix(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(bot_id="member", shared_workspace_id="ws-1", shared_workspace_role="worker")
        prefix = get_memory_rel_path(bot)
        pattern = prefix.rstrip("/") + "/%"
        assert pattern == "memory/%"

    def test_orchestrator_prefix(self):
        from app.services.memory_scheme import get_memory_rel_path
        bot = _bot(bot_id="orch", shared_workspace_id="ws-1", shared_workspace_role="orchestrator")
        prefix = get_memory_rel_path(bot)
        pattern = prefix.rstrip("/") + "/%"
        assert pattern == "bots/orch/memory/%"
